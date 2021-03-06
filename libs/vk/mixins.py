# coding=utf8

import logging

from . exceptions import VkAuthError
from . utils import raw_input, get_url_query, LoggingSession, get_form_action


logger = logging.getLogger('vk')


class AuthMixin(object):
    LOGIN_URL = 'https://m.vk.com'
    # REDIRECT_URI = 'https://oauth.vk.com/blank.html'
    AUTHORIZE_URL = 'https://oauth.vk.com/authorize'
    CAPTCHA_URI = 'https://m.vk.com/captcha.php'

    def __init__(self, app_id=None, user_login='', user_password='', scope='offline', key=None, **kwargs):
        logger.debug('AuthMixin.__init__(app_id=%(app_id)r, user_login=%(user_login)r, user_password=%(user_password)r, 2fa_key=%(key)s, **kwargs=%(kwargs)s)',
            dict(app_id=app_id, user_login=user_login, user_password=user_password, key=key, kwargs=kwargs))

        super(AuthMixin, self).__init__(**kwargs)

        self.app_id = app_id
        self.user_login = user_login
        self.user_password = user_password
        self.scope = scope
        self.key = key

        # Some API methods get args (e.g. user id) from access token.
        # If we define user login, we need get access token now.
        if self.user_login:
            self.access_token = self.get_access_token()

    @property
    def user_login(self):
        if not self._user_login:
            self._user_login = self.get_user_login()
        return self._user_login

    @user_login.setter
    def user_login(self, value):
        self._user_login = value

    def get_user_login(self):
        return self._user_login

    @property
    def user_password(self):
        if not self._user_password:
            self._user_password = self.get_user_password()
        return self._user_password

    @user_password.setter
    def user_password(self, value):
        self._user_password = value

    def get_user_password(self):
        return self._user_password
    
    def get_access_token(self):
        """
        Get access token using app id and user login and password.
        """
        logger.debug('AuthMixin.get_access_token()')

        auth_session = LoggingSession()
        with auth_session as self.auth_session:
            self.auth_session = auth_session
            self.login()
            auth_response_url_query = self.oauth2_authorization()

        if 'access_token' in auth_response_url_query:
            return auth_response_url_query['access_token']
        else:
            raise VkAuthError('OAuth2 authorization error')

    def login(self):
        """
        Login
        """

        response = self.auth_session.get(self.LOGIN_URL)
        login_form_action = get_form_action(response.text)
        if not login_form_action:
            raise VkAuthError('VK changed login flow')

        login_form_data = {
            'email': self.user_login,
            'pass': self.user_password,
        }
        response = self.auth_session.post(login_form_action, login_form_data)
        logger.debug('Cookies: %s', self.auth_session.cookies)

        response_url_query = get_url_query(response.url)

        if 'remixsid' in self.auth_session.cookies or 'remixsid6' in self.auth_session.cookies:
            return

        if 'sid' in response_url_query:
            self.auth_captcha_is_needed(response, login_form_data)
        elif response_url_query.get('act') == 'authcheck':
            self.auth_check_is_needed(response.text)
        elif 'security_check' in response_url_query:
            self.phone_number_is_needed(response.text)
        else:
            message = 'Authorization error (incorrect password)'
            logger.error(message)
            raise VkAuthError(message)

    def oauth2_authorization(self):
        """
        OAuth2
        """
        auth_data = {
            'client_id': self.app_id,
            'display': 'mobile',
            'response_type': 'token',
            'scope': self.scope,
            'v': '5.28',
        }
        response = self.auth_session.post(self.AUTHORIZE_URL, auth_data)
        response_url_query = get_url_query(response.url)
        if 'access_token' in response_url_query:
            return response_url_query

        # Permissions is needed
        logger.debug('Getting permissions')
        # form_action = re.findall(r'<form method="post" action="(.+?)">', auth_response.text)[0]
        form_action = get_form_action(response.text)
        logger.debug('Response form action: %s', form_action)
        if form_action:
            response = self.auth_session.get(form_action)
            response_url_query = get_url_query(response.url)
            return response_url_query

        try:
            response_json = response.json()
        except ValueError:  # not JSON in response
            error_message = 'OAuth2 grant access error'
        else:
            error_message = 'VK error: [{}] {}'.format(response_json['error'], response_json['error_description'])
        logger.error('Permissions obtained')
        raise VkAuthError(error_message)

    def auth_check_is_needed(self, html):
        logger.debug('User enabled 2 factors authorization. Auth check code is needed')
        action_url = get_form_action(html)
        auth_check_code = self.get_auth_check_code()
        auth_check_data = {
            'code': auth_check_code,
            '_ajax': '1',
            'remember': '1'
        }
        url = '/'.join([self.LOGIN_URL + action_url])
        response = self.auth_session.post(url=url, data=auth_check_data)
        return response

    def auth_captcha_is_needed(self, response, login_form_data):
        logger.info('Captcha is needed')

        response_url_dict = get_url_query(response.url)

        # form_url = re.findall(r'<form method="post" action="(.+)" novalidate>', response.text)
        captcha_form_action = get_form_action(response.text)
        logger.debug('form_url %s', captcha_form_action)
        if not captcha_form_action:
            raise VkAuthError('Cannot find form url')

        # todo Are we sure that `response_url_dict` doesn't contain CAPTCHA image url?
        captcha_url = '%s?s=%s&sid=%s' % (self.CAPTCHA_URI, response_url_dict['s'], response_url_dict['sid'])
        # logger.debug('Captcha url %s', captcha_url)

        login_form_data['captcha_sid'] = response_url_dict['sid']
        login_form_data['captcha_key'] = self.get_captcha_key(captcha_url)

        response = self.auth_session.post(captcha_form_action, login_form_data)

        # logger.debug('Cookies %s', self.auth_session.cookies)
        # if 'remixsid' not in self.auth_session.cookies and 'remixsid6' not in self.auth_session.cookies:
        #     raise VkAuthError('Authorization error (Bad password or captcha key)')

    def phone_number_is_needed(self, text):
        raise VkAuthError('Phone number is needed')

    def get_auth_check_code(self):
        if self.key:
            return self.key # raw_input('key:')
        raise VkAuthError('Auth check code is needed')
