"""
Define some view level utility functions here that multiple view modules will share
"""
from __future__ import absolute_import

from collections import OrderedDict
from contextlib import contextmanager

from django.contrib.auth import get_user_model
from django.db.models import Q
from rest_framework import status
from rest_framework.exceptions import AuthenticationFailed
from rest_framework.pagination import CursorPagination
from rest_framework.response import Response

from lms.djangoapps.grades.course_grade_factory import CourseGradeFactory
from openedx.core.lib.api.view_utils import DeveloperErrorViewMixin
from student.models import CourseEnrollment
from util.query import use_read_replica_if_available

USER_MODEL = get_user_model()


class CourseEnrollmentPagination(CursorPagination):
    """
    Paginates over CourseEnrollment objects.
    """
    ordering = 'id'
    page_size = 50
    page_size_query_param = 'page_size'

    def get_page_size(self, request):
        """
        Get the page size based on the defined page size parameter if defined.
        """
        try:
            page_size_string = request.query_params[self.page_size_query_param]
            return int(page_size_string)
        except (KeyError, ValueError):
            pass

        return self.page_size

    def get_paginated_response(self, data, **kwargs):  # pylint: disable=arguments-differ
        """
        Return a response given serialized page data and kwargs. Each key-value pair is added to the response.
        """
        resp = OrderedDict([
            ('next', self.get_next_link()),
            ('previous', self.get_previous_link()),
            ('results', data)
        ])

        for (key, value) in kwargs.items():
            resp[key] = value

        return Response(resp)


class GradeViewMixin(DeveloperErrorViewMixin):
    """
    Mixin class for Grades related views.
    """
    def _get_single_user(self, request, course_key, user_id=None):
        """
        Returns a single USER_MODEL object corresponding to either the user_id provided, or if no id is provided,
        then the request's `username` parameter, or the current `request.user` if no `username` was provided.

        Args:
            request (Request): django request object to check for username or request.user object
            course_key (CourseLocator): The course to retrieve user grades for.
            user_id (int): Optional user id to fetch the user object for.

        Returns:
            A USER_MODEL object.

        Raises:
            USER_MODEL.DoesNotExist if no such user exists.
            CourseEnrollment.DoesNotExist if the user is not enrolled in the given course.
        """
        # May raise USER_MODEL.DoesNotExist if no user matching the given query exists.
        if user_id:
            grade_user = USER_MODEL.objects.get(id=user_id)
        elif 'username' in request.GET:
            grade_user = USER_MODEL.objects.get(username=request.GET.get('username'))
        else:
            grade_user = request.user

        # May raise CourseEnrollment.DoesNotExist if no enrollment exists for this user/course.
        _ = CourseEnrollment.objects.get(user=grade_user, course_id=course_key)

        return grade_user

    @contextmanager
    def _get_user_or_raise(self, request, course_key):
        """
        Raises an API error if the username specified by the request does not exist, or if the
        user is not enrolled in the given course.
        Args:
            request (Request): django request object to check for username or request.user object
            course_key (CourseLocator): The course to retrieve user grades for.

        Yields:
            A USER_MODEL object.
        """
        try:
            yield self._get_single_user(request, course_key)
        except USER_MODEL.DoesNotExist:
            raise self.api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                developer_message='The user matching the requested username does not exist.',
                error_code='user_does_not_exist'
            )
        except CourseEnrollment.DoesNotExist:
            raise self.api_error(
                status_code=status.HTTP_404_NOT_FOUND,
                developer_message='The user matching the requested username is not enrolled in this course',
                error_code='user_not_enrolled'
            )

    def _get_single_user_grade(self, grade_user, course_key):
        """
        Returns a grade response for the user object corresponding to the request's 'username' parameter,
        or the current request.user if no 'username' was provided.
        Args:
            request (Request): django request object to check for username or request.user object
            course_key (CourseLocator): The course to retrieve user grades for.

        Returns:
            A serializable list of grade responses
        """
        course_grade = CourseGradeFactory().read(grade_user, course_key=course_key)
        return Response([self._serialize_user_grade(grade_user, course_key, course_grade)])

    def _paginate_users(self, course_key, course_enrollment_filter=None, related_models=None):
        """
        Args:
            course_key (CourseLocator): The course to retrieve grades for.
            course_enrollment_filter: Optional list of Q objects to pass
            to `CourseEnrollment.filter()`.
            related_models: Optional list of related models to join to the CourseEnrollment table.

        Returns:
            A list of users, pulled from a paginated queryset of enrollments, who are enrolled in the given course.
        """
        filter_args = [
            Q(course_id=course_key) & Q(is_active=True)
        ]
        filter_args.extend(course_enrollment_filter or [])

        enrollments_in_course = use_read_replica_if_available(
            CourseEnrollment.objects.filter(*filter_args)
        )
        if related_models:
            enrollments_in_course = enrollments_in_course.select_related(*related_models)

        paged_enrollments = self.paginate_queryset(enrollments_in_course)
        retlist = []
        for enrollment in paged_enrollments:
            enrollment.user.enrollment_mode = enrollment.mode
            retlist.append(enrollment.user)
        return retlist

    def _serialize_user_grade(self, user, course_key, course_grade):
        """
        Serialize a single grade to dict to use in Responses
        """
        return {
            'username': user.username,
            # per business requirements, email should only be visible for students in masters track only
            'email': user.email if getattr(user, 'enrollment_mode', '') == 'masters' else '',
            'course_id': str(course_key),
            'passed': course_grade.passed,
            'percent': course_grade.percent,
            'letter_grade': course_grade.letter_grade,
        }

    def perform_authentication(self, request):
        """
        Ensures that the user is authenticated (e.g. not an AnonymousUser).
        """
        super(GradeViewMixin, self).perform_authentication(request)
        if request.user.is_anonymous:
            raise AuthenticationFailed
