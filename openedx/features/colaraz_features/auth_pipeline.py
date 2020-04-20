"""
Social Auth Pipeline methods for Colaraz's customizations
"""
from cms.djangoapps.course_creators.models import CourseCreator
from student.models import CourseAccessRole


def manage_user_roles(response, user=None, *args, **kwargs):
    """
    Assuming that the following kind of data in provided by IdP
    {
        'email': 'testuser101@emailnube.com',
        'firstName': 'changed_first1',
        'lastName': 'changed_last1',
        "companyInfo": {
            "name": "UET",
            "url": "test"
        },
        "isCourseCreator": true,
        "roles":[
            {
                "role": "course_creator_group",
                "orgs": ["uet", "lums"]
            }, {
                "role": "staff",
                "orgs": ["uet", "lums"]
            }, {
                "role": "instructor",
                "orgs": ["uet", "lums"]
            }
        ]
    }
    """

    if not user:
        return 
    else:
        update_course_creator_group(user, response.get('isCourseCreator'))
        if response.get('roles'):
            update_user_roles(user, response.get('roles'))

        return


def update_course_creator_group(user, is_course_creator):
    """
    Updates course creator access of Users
    """
    params = {'admin': user}
    params['state'] = CourseCreator.GRANTED if is_course_creator else CourseCreator.DENIED

    instance, created = CourseCreator.objects.update_or_create(user=user, defaults=params)

def update_user_roles(user, access_roles):
    """
    Traverses through all the roles and updates them, depending upon the data
    recieved from IdP
    """
    for access_role in access_roles:
        role = access_role.get('role')
        orgs = access_role.get('orgs')
        if orgs and role:
            exisitng_roles = CourseAccessRole.objects.filter(user_id=user.id, role=role)
            for role in exisitng_roles:
                if role.org not in orgs:
                    role.delete()
                else:
                    orgs.remove(role.org)
            for org in orgs:
                CourseAccessRole.objects.create(user_id=user.id, role=role, org=org)
