import logging

from django.utils.functional import cached_property
from social_core.exceptions import AuthException

from openedx.core.djangoapps.theming.helpers import get_current_request
from openedx.features.colaraz_features.helpers import register_user_from_mobile_request

from third_party_auth.identityserver3 import IdentityServer3

LOGGER = logging.getLogger(__name__)


class ColarazIdentityServer(IdentityServer3):
    """
    An extension of the IdentityServer3 for use with Colaraz's IdP service.
    """
    name = "colarazIdentityServer"
    DEFAULT_SCOPE = ["openid", "profile", "IdentityServerApi"]
    ID_KEY = "email"

    def get_redirect_uri(self, state=None):
        """
        Returns redirect uri for oauth redirection
        """
        current_req = get_current_request()

        environ = getattr(current_req, "environ", {})
        schema = environ.get("wsgi.url_scheme", "http")

        site = getattr(current_req, "site", None)
        domain = getattr(site, "domain", None)

        if not domain:
            LOGGER.exception("Domain not found in request attributes")
            raise AuthException("Colaraz", "Error while authentication")

        return "{}://{}/auth/complete/{}".format(schema, domain, self.name)

    def get_user_details(self, response):
        """
        Returns detail about the user account from the service
        """

        current_req = get_current_request()
        site = getattr(current_req, "site", None)
        domain = getattr(site, "domain", None)
        try:
            user_site_domain = response["companyInfo"]["url"]

            if not domain:
                LOGGER.exception("Domain not found in request attributes")
                raise AuthException("Colaraz", "Error while authentication")
            elif user_site_domain.lower() not in domain:
                LOGGER.exception("User can only login through {} site".format(user_site_domain))
                raise AuthException("Colaraz", "Your account belongs to {}".format(user_site_domain))

            details = {
                "fullname": u"{} {}".format(response["firstName"], response["lastName"]).encode("ascii", "ignore"),
                "email": response["email"],
                "first_name": response["firstName"],
                "last_name": response["lastName"],
                "username": response["email"]
            }
            return details
        except KeyError:
            LOGGER.exception("User profile data is unappropriate or not given")
            raise AuthException("Colaraz", "User profile data is unappropriate or not given")

    @cached_property
    def _id3_config(self):
        from third_party_auth.models import OAuth2ProviderConfig
        return OAuth2ProviderConfig.current(self.name)

    def user_data(self, access_token, *args, **kwargs):
        """
        Returns the user data receive by social backend and register in case of user doesn't exists already.
        """

        # Imported here to avoid circular imports
        from third_party_auth.utils import user_exists

        user_data = super(ColarazIdentityServer, self).user_data(access_token, *args, **kwargs)
        request = get_current_request()
        request_source = request.GET.get('src')

        if (request.view_name == "AccessTokenExchangeView" and
                request_source == 'mobile' and
                not user_exists(user_data)):
            LOGGER.info("Received request from mobile and now registering a new user.")
            user = register_user_from_mobile_request(request, user_data)

        return user_data
