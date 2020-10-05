"""
Views for colaraz API.
"""
import json
import logging
import requests
from six.moves.urllib.parse import urlencode

from django.conf import settings

from rest_framework import viewsets, status
from rest_framework_oauth.authentication import OAuth2Authentication
from rest_framework.authentication import SessionAuthentication
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework import serializers as rest_serializers

from openedx.features.colaraz_features.api import serializers
from openedx.features.course_experience.utils import get_course_outline_block_tree
from xmodule.modulestore.exceptions import ItemNotFoundError

LOGGER = logging.getLogger(__name__)


class SiteOrgViewSet(viewsets.ViewSet):
    """
    View set to enable creation of site, organization and theme via REST API.
    """

    serializer_class = serializers.SiteOrgSerializer

    def create(self, request):
        """
        Perform creation operation for site, organization, site theme and site configuration.
        """
        try:
            serializer = self.serializer_class(data=request.data)
            if serializer.is_valid(raise_exception=True):
                data = serializer.create(serializer.validated_data)
        except (rest_serializers.ValidationError, ValueError, NameError) as ex:
            return Response(
                {'error': str(ex)},
                status=status.HTTP_400_BAD_REQUEST
            )
        except:
            return Response(
                {'error': 'Request data is unappropriate'},
                status=status.HTTP_400_BAD_REQUEST
            )

        return Response(
            {'success': data},
            status=status.HTTP_201_CREATED
        )


class NotificationHandlerApiView(APIView):
    """
    APIView to fetch notifications and mark them as read.
    """
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    API_METHODS = {
        'fetch': 'METHOD_FETCH_NOTIFICATIONS',
        'mark': 'METHOD_MARK_NOTIFICATIONS',
    }

    def get(self, request, api_method, format=None):
        """
        This method uses Colaraz's Notifications API to fetch and mark notifications
        and returns data sent by API in json format.

        The response we get while fetching notifications is of the following pattern:
        {
            "status": 0,
            "result": [
                {
                    "from_guid": "<FROM GUID>",
                    "description": "<SOME HTML CONTENT>",
                    "time": "<RELATIVE TIME>",
                    "image": "<IMAGE SRC>",
                    "read": <STATUS REGARDING ITS READ/UNREAD STATE>
                }
            ]
        }
        """
        elgg_id = request.user.colaraz_profile.elgg_id
        api_details = getattr(settings, 'COLARAZ_NOTIFICATIONS', {})
        is_enabled = api_details.get('ENABLE', False)
        method_key = self.API_METHODS.get(api_method)

        if is_enabled and elgg_id and method_key:
            api_url = api_details.get('API_URL')
            query_params = urlencode({
                'api_key': api_details.get('API_KEY'),
                'guid': elgg_id,
                'method': api_details.get(method_key),
            })

            resp = requests.get(api_url, params=query_params)
            if resp.status_code == status.HTTP_200_OK:
                json_data = json.loads(resp.content)
                if json_data.get('status') == 0:
                    return Response(json_data, status=status.HTTP_200_OK)
                else:
                    LOGGER.error('Notifications API gave error: {}'.format(json_data.get('message')))
                    return Response(json_data, status=status.HTTP_400_BAD_REQUEST)
            else:
                LOGGER.error('Notifications API returned {} status'.format(resp.status_code))
        else:
            LOGGER.error('Notifications API is not enabled or is not configured properly')
        return Response(
            {'message': 'Notifications API is not enabled or is not configured properly'},
            status=status.HTTP_400_BAD_REQUEST
        )


class JobAlertsHandlerApiView(APIView):
    """
    APIView to fetch job alerts and mark them as read.
    """
    authentication_classes = (SessionAuthentication,)
    permission_classes = (IsAuthenticated,)

    API_ENDPOINTS = {
        'fetch': 'FETCH_URL',
        'mark': 'MARK_URL'
    }

    def get(self, request, api_method, format=None):
        """
        This method uses Colaraz's Job Alerts API to fetch and mark alerts
        and returns data sent by API in json format.

        The response we get while fetching job alerts is of the following pattern:
        {
            "d": [
                {
                    "__type": "<SOME TYPE IDENTIFIER>",
                    "Heading": "<JOB HEADING>",
                    "Message": "<JOB MESSAGE>",
                    "RelativeTime": "<RELATIVE TIME OF ALERT>",
                    "NotificationType": <NOTIFICATION TYPE IDENTIFIER>
                }
            ]
        }
        """
        email_id = request.user.email
        api_details = getattr(settings, 'COLARAZ_JOB_ALERTS', {})
        is_enabled = api_details.get('ENABLE', False)
        method_key = self.API_ENDPOINTS.get(api_method)
        api_url = api_details.get(method_key)

        if is_enabled and email_id and api_url:
            resp = requests.post(api_url, json={'email': email_id})
            if resp.status_code == status.HTTP_200_OK:
                json_data = json.loads(resp.content)
                return Response(json_data, status=status.HTTP_200_OK)
            else:
                LOGGER.error('Job Alerts API returned status: "{}"'.format(
                        resp.status_code,
                    )
                )
        else:
            LOGGER.error('Job Alerts API is not enabled or is not configured properly')

        return Response(
            {'message': 'Job Alerts API is not enabled or is not configured properly'},
            status=status.HTTP_400_BAD_REQUEST
        )


class CourseOutlineView(APIView):
    authentication_classes = (OAuth2Authentication, )
    permission_classes = (IsAuthenticated,)

    def get(self, request, course_id):
        """
        api to get course outline in sequence
        :param request:
        :param course_id:
        :return: dictionary of course outline tree structure
        """
        user = request.user
        try:
            course_tree = get_course_outline_block_tree(request, course_id, user)
        except ItemNotFoundError:
            # this exception is raised in few cases like if invalid course_id is passed
            return Response(data='Course not found', status=status.HTTP_404_NOT_FOUND)
        if course_tree is None:
            return Response(data='Course not found', status=status.HTTP_404_NOT_FOUND)
        return Response(course_tree, status=status.HTTP_200_OK)

