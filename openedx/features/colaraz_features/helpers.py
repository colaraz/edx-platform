"""
Helper functions for colaraz app.
"""
import json
import logging
from collections import namedtuple

import requests
from six import text_type
from six.moves.urllib.parse import urlencode

from django import forms
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.sites.models import Site
from django.db.models import Q
from django.http import QueryDict
from opaque_keys import InvalidKeyError
from opaque_keys.edx.django.models import CourseKeyField
from opaque_keys.edx.locator import CourseKey
from openedx.core.djangoapps.site_configuration.models import SiteConfiguration
from openedx.core.djangoapps.theming.models import SiteTheme
from openedx.features.colaraz_features.constants import (
    ALL_ORGANIZATIONS_MARKER,
    COURSE_ACCESS_ROLES_DISPLAY_MAPPING,
    ROLES_FOR_LMS_ADMIN
)
from organizations.models import Organization
from student.models import CourseAccessRole, UserProfile
from student.roles import CourseCreatorRole, OrgRoleManagerRole
from xmodule.modulestore.django import modulestore

if settings.ROOT_URLCONF == 'lms.urls':
    from cms.djangoapps.course_creators.models import CourseCreator
else:
    from course_creators.models import CourseCreator

# Tuple containing information for lms and studio
# This named tuple can be used for sites, site themes, organizations etc.
Pair = namedtuple('Pair', 'lms studio')
LMS_AND_STUDIO_SITE_PREFIXES = ('courses', 'studio')
LOGGER = logging.getLogger(__name__)


def do_sites_exists(domain):
    """
    Check if either lms or studio site for the given domain name exist.

    Arguments:
        domain (str): Domain to identify the site. e.g. example.com, test.example.com etc.

    Returns:
        (bool): True if lms and studio sites do not exist for the given domain, False otherwise.
    """
    return Site.objects.filter(
        domain__in=['{}.{}'.format(prefix, domain) for prefix in LMS_AND_STUDIO_SITE_PREFIXES]
    ).exists()


def remove_duplicates(items):
    """
    Remove duplicate items from the argument list.

    The function will not work if the items in the provided list are not hashable.

    Arguments:
        (list): List of hashable items from which to remove duplicates.

    Returns:
        (list): List of items containing only unique items.
    """
    return list(set(items))


def create_sites(domain, name):
    """
    Create sites for lms and studio with domain and name provided in the arguments.

    LMS Domain will be formed by prepending `courses` to the passed in domain. And Studio domain will be
    formed by prepending `studio` to the passed in domain.

    Arguments:
        domain (str): Domain to identify the site. e.g. example.com, test.example.com etc.
        name (str): Human readable name for the site.

    Returns:
        (Pair<Site, Site>): named tuple containing lms, studio sites.
    """
    sites = (
        Site.objects.create(
            domain='{}.{}'.format(prefix, domain),
            name='{}.{}'.format(prefix, name),
        ) for prefix in LMS_AND_STUDIO_SITE_PREFIXES
    )
    return Pair(*sites)


def create_site_themes(sites, theme):
    """
    Create site themes for the site provided in the arguments.

    Arguments:
        sites (Pair<Site, Site>): Named tuple containing lms and studio sites.
        theme (str): Theme name to be added for the sites.
    Returns:
        (Pair<SiteTheme, SiteTheme>): named tuple containing lms, studio sites themes.
    """
    site_themes = (
        SiteTheme.objects.create(
            site=site,
            theme_dir_name=theme
        ) for site in sites
    )
    return Pair(*site_themes)


def create_organization(name, short_name):
    """
    Create an organization with the given name.

    Short name for the organization will be extracted from the name by slugify-ing the name.

    Arguments:
        name (str): Name of the organization to create.
        short_name (str): Short name of the organization to create.

    Returns:
        (organization.Organization): Instance of the newly created organization.
    """
    return Organization.objects.create(
        name=name,
        short_name=short_name,
    )


def create_site_configurations(sites, organization, university_name, platform_name, organizations):
    """
    Create site configurations for the given sites.

    Following fields will be set in the configuration
        1. SESSION_COOKIE_DOMAIN: site.domain
        2. PLATFORM_NAME: platform_name
        3. site_domain: site.domain
        4. site_name: university_name
        5. course_org_filters: [ organization.short_name ] + organizations

    Arguments:
        sites (Pair<Site, Site>): named tuple containing lms and studio sites for which to create the configuration.
        organization (organization.Organization): Organization to associate with the configuration.
        university_name (str): Name of the university
        platform_name (str): Platform name that appears on the dashboard and several other places.
        organizations ([str]): List of organizations to add in the configuration.

    Returns:
        (Pair<SiteConfiguration, SiteConfiguration>): named tuple containing lms, studio sites configurations.
    """
    site_configurations = (
        SiteConfiguration.objects.create(
            site=site,
            enabled=True,
            values=dict(
                SESSION_COOKIE_DOMAIN=site.domain,
                PLATFORM_NAME=platform_name,
                platform_name=platform_name,
                site_domain=site.domain,
                SITE_NAME=site.domain,
                university=university_name,
                course_org_filters=remove_duplicates(organizations + [organization.short_name]),
                **(
                    {
                        'AUTH_PROVIDER_FALLBACK_URL': 'https://{}'.format(sites.lms.domain)
                    } if site == sites.studio else {}
                )
            )
        ) for site in sites
    )
    return Pair(*site_configurations)


def get_request_schema(request):
    """
    Returns schema of request
    """
    environ = getattr(request, "environ", {})
    return environ.get("wsgi.url_scheme", "http")


def get_site_base_url(request):
    """
    Returns current request's complete url
    """
    schema = get_request_schema(request)
    domain = get_request_site_domain(request)

    return '{}://{}'.format(schema, domain)


def get_request_site_domain(request):
    """
    Returns domain of site being requested by the User.
    """
    site = getattr(request, 'site', None)
    domain = getattr(site, 'domain', None)
    return domain


def get_user_organizations(user):
    """
    Get a set of all the organizations for which given user has access role of role manager.

    Arguments:
        user (User): Djnago user object.

    Returns:
        (set): A set of organizations, given user has role manager access of.
    """

    return set(
        user.courseaccessrole_set.filter(
            role=OrgRoleManagerRole.ROLE,
            course_id=CourseKeyField.Empty
        ).exclude(
            org__exact=''
        ).values_list('org', flat=True)
    )


def get_organization_users(organizations, search,  page=1, page_size=100):
    """
    Return all the users belonging to the set if given organizations.

    Arguments:
        organizations (set): A Set of organizations.
        search (str): Search parameter to for email based searching.
        page (int): Cursor denoting the page to fetch.
        page_size (int): Page size, defaulting to 100.
    Returns:
        (list<User>, bool): tuple of a List of users who belong the given organizations and
            a boolean showing if more records are present.
    """
    queryset = User.objects
    start = (page - 1) * page_size
    limit = start + page_size

    if ALL_ORGANIZATIONS_MARKER not in organizations:
        # Filter based on organizations if we do not want to include users from all organizations.
        queryset = queryset.filter(colaraz_profile__site_identifier__in=organizations)
    if search:
        queryset = queryset.filter(email__icontains=search)

    q = queryset.all()[start:limit + 1]  # +1 to check if more records are present after this page.
    queryset = queryset.all()[start:limit]
    return queryset.all(), q.count() > page_size


def validate_course_id(course_id):
    """
    Validate course id and return the corresponding CourseKey object.

    Arguments:
        course_id (str): Course identifier

    Raises:
        (forms.ValidationError): if Given course jey is not valid or does not point to an existing course.

    Returns:
        (CourseKey): CourseKey object against the given course identifier.
    """
    try:
        course_key = CourseKey.from_string(course_id)
    except InvalidKeyError:
        msg = u'Course id invalid. Entered course id was: "{0}".'.format(course_id)
        raise forms.ValidationError(msg)

    if not modulestore().has_course(course_key):
        msg = u'Course not found. Entered course id was: "{0}".'.format(text_type(course_key))
        raise forms.ValidationError(msg)

    return course_key


def get_or_create_course_access_role(staff, user_id, org, role, course_id=CourseKeyField.Empty):
    """
    Call get_or_create on `CourseAccessRole` model.

    This method is placed here to create `CourseCreator` model instances along with newly create course_creator_group
    access roles.
    """
    instance, is_created = CourseAccessRole.objects.get_or_create(
        user_id=user_id,
        org=org,
        role=role,
        course_id=course_id
    )

    if is_created:
        update_or_create_course_creator(instance.user, staff)

    return instance


def bulk_create_course_access_role(staff, user_id, org, roles, course_ids, created_roles=[]):
    """
    bulk create `CourseAccessRole` model instances.

    This method is placed here to create `CourseCreator` model instances along with newly create course_creator_group
    access roles.
    """
    def handle_course_creator_group():
        try:
            user_account = User.objects.get(id=user_id)
        except User.DoesNotExist:
            return []
        if CourseCreatorRole.ROLE in roles:
            instance, _ = CourseAccessRole.objects.get_or_create(
                course_id=CourseKeyField.Empty,
                org='',
                role=CourseCreatorRole.ROLE,
                user_id=user_id
            )
            created_roles.append(instance)
            update_or_create_course_creator(user_account, staff)
            roles.remove(CourseCreatorRole.ROLE)
        return roles

    def handle_org_roles():
        course_roles = []
        for role in roles:
            if role.startswith('org_'):
                org_role = role.replace('org_', '', 1)
                instance, _ = CourseAccessRole.objects.get_or_create(
                    course_id=CourseKeyField.Empty,
                    org=org,
                    role=org_role,
                    user_id=user_id,
                )
                created_roles.append(instance)
            else:
                course_roles.append(role)
        return course_roles

    def handle_course_roles():
        for course_id in course_ids:
            for role in roles:
                instance, _ = CourseAccessRole.objects.get_or_create(
                    user_id=user_id,
                    org=org,
                    role=role,
                    course_id=course_id,
                )
                created_roles.append(instance)

    roles = handle_course_creator_group()
    roles = handle_org_roles()
    if course_ids:
        handle_course_roles()

    return created_roles


def update_or_create_course_creator(user, staff):
    """
    Call update_or_create on `CourseCreator` with appropriate arguments.
    """
    try:
        obj = CourseCreator.objects.get(user=user)
    except CourseCreator.DoesNotExist:
        # Nothing to revoke, as user's access does not exist.
        obj = CourseCreator(user=user)

    obj.state = CourseCreator.GRANTED
    obj.admin = staff
    obj.save()


def revoke_course_creator_access(user, staff):
    """
    Revoke course creator access for the given user.
    """
    try:
        obj = CourseCreator.objects.get(user=user)
    except CourseCreator.DoesNotExist:
        # Nothing to revoke, as user's access does not exist.
        pass
    else:
        obj.state = CourseCreator.DENIED
        obj.admin = staff
        obj.save()


def notify_access_role_deleted(role, actor):
    """
    Perform required operations once course access role is deleted.
    """
    if role.role == CourseCreatorRole.ROLE:
        revoke_course_creator_access(role.user, actor)


def make_user_lms_admin(user, org):
    """
    This function is meant to map users with respect to their lms_admin role
    sent by Colaraz's IdP

    Arguments:
        user (User): Django user for which to assign roles
        org (str): Organization of the user

    Returns:
        (bool): True for success, False for failure.
    """
    if not org:
        return False

    queryset = user.courseaccessrole_set.filter(
        role__in=ROLES_FOR_LMS_ADMIN,
        org=org,
    )

    if queryset.count() == len(ROLES_FOR_LMS_ADMIN):
        # Nothing to do, user is already an lms admin for given organization.
        return True

    # If any of the lms admin role already exist then make an update and assign other roles.
    instance = user.courseaccessrole_set.filter(
        role__in=ROLES_FOR_LMS_ADMIN,
        org=org,
    ).first()

    # Import is placed here to avoid cicular import
    from openedx.features.colaraz_features.forms import ColarazCourseAccessRoleForm
    kwargs = {
        'user': user,
        'instance': instance,
        'data': get_query_dict({
            'user': user.id,
            'org': org,
            'roles': ROLES_FOR_LMS_ADMIN,
            'course_ids': [],
        }),
    }
    form = ColarazCourseAccessRoleForm(**kwargs)
    if form.is_valid():
        form.save()
        return True
    return False


def get_query_dict(_dict):
    """
    Create QueryDict object from the given dict.
    """
    q = QueryDict(mutable=True)
    for key, value in _dict.items():
        if isinstance(value, (list, set)):
            q.setlist(key, value)
        else:
            q[key] = value
    return q


def get_role_based_urls(response):
    email = response.get('email')
    access_token = response.get('access_token')
    if email and access_token and hasattr(settings, 'COLARAZ_APP_LINKS_API_URL'):
        api_url = '{}?{}'.format(settings.COLARAZ_APP_LINKS_API_URL, urlencode({'email': email}))
        resp = requests.get(api_url, headers={'Authorization': 'Bearer {}'.format(access_token)})
        if resp.status_code == 200:
            return json.loads(resp.content)
        else:
            LOGGER.error('Colaraz app links api responded with status code: {}'.format(resp.status_code))
    else:
        LOGGER.error('Parameters required to call Colaraz app links api were not complete')
    return {}

def get_course_access_role_display_name(course_access_role):
    role_name = course_access_role.role if course_access_role.course_id \
        or course_access_role.role == CourseCreatorRole.ROLE else 'org_{}'.format(course_access_role.role)
    return COURSE_ACCESS_ROLES_DISPLAY_MAPPING.get(role_name)

def add_user_fullname_in_threads(threads):
    if not isinstance(threads, list):
        tmp_list = []
        tmp_list.append(threads)
        threads = tmp_list

    name_map = {}
    thread_usernames = [thread['username'] for thread in threads if thread.has_key('username')]
    profile_usernames = UserProfile.objects.filter(user__username__in=thread_usernames)\
       .values_list('user__username', 'name')
    for profile_username in profile_usernames:
        name_map[profile_username[0]] = profile_username[1]

    for thread in threads:
        if thread.has_key('username'):
            thread['fullname'] = name_map[thread['username']] or 'Anonymous'
        if len(thread.get('children', [])) > 0:
            thread['children'] = add_user_fullname_in_threads(thread.get('children'))
        if thread.get('endorsement'):
            add_user_fullname_in_threads(thread.get('endorsement'))

    return threads


def has_admin_access(request, course_id):
    """
    Checks that colaraz user has instructor/staff level privileges or not.
    """
    user_org = request.user.colaraz_profile.site_identifier
    return request.user.courseaccessrole_set.filter((Q(course_id=course_id)
                                                    | Q(course_id=CourseKeyField.Empty, org__iexact=user_org))
                                                    & Q(role__in=['instructor', 'staff'])).exists()
