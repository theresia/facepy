import requests

from .exceptions import FacebookError, OAuthError

try:
    import simplejson as json
except ImportError:
    import json


class GraphAPI(object):

    def __init__(self, oauth_token=False, url='https://graph.facebook.com'):
        """
        Initialize GraphAPI with an OAuth access token.

        :param oauth_token: A string describing an OAuth access token.
        """
        self.oauth_token = oauth_token
        self.session = requests.session()
        self.url = url.strip('/')

    def get(self, path='', page=False, retry=3, **options):
        """
        Get an item from the Graph API.

        :param path: A string describing the path to the item.
        :param page: A boolean describing whether to return a generator that
                     iterates over each page of results.
        :param options: Graph API parameters such as 'limit', 'offset' or 'since'.

        See `Facebook's Graph API documentation <http://developers.facebook.com/docs/reference/api/>`_
        for an exhaustive list of parameters.
        """
        response = self._query('GET', path, options, page)

        if isinstance(response, Exception):
            if retry > 1:
                retry -= 1
                return self.get(path, page, retry, **options)
            else:
                raise response

        if response is False:
            raise FacebookError('Could not get "%s".' % path)

        return response

    def post(self, path='', **data):
        """
        Post an item to the Graph API.

        :param path: A string describing the path to the item.
        :param options: Graph API parameters.

        See `Facebook's Graph API documentation <http://developers.facebook.com/docs/reference/api/>`_
        for an exhaustive list of options.
        """

        response = self._query('POST', path, data)

        if response is False:
            raise FacebookError('Could not post to "%s"' % path)

        return response

    def delete(self, path):
        """
        Delete an item in the Graph API.

        :param path: A string describing the path to the item.
        """

        response = self._query('DELETE', path)

        if response is False:
            raise FacebookError('Could not delete "%s"' % path)

        return response

    def search(self, term, type, page=False, **options):
        """
        Search for an item in the Graph API.

        :param term: A string describing the search term.
        :param type: A string describing the type of items to search for.
        :param page: A boolean describing whether to return a generator that
                     iterates over each page of results.
        :param options: Graph API parameters, such as 'center' and 'distance'.

        Supported types are ``post``, ``user``, ``page``, ``event``, ``group``, ``place`` and ``checkin``.

        See `Facebook's Graph API documentation <http://developers.facebook.com/docs/reference/api/>`_
        for an exhaustive list of options.
        """

        SUPPORTED_TYPES = ['post', 'user', 'page', 'event', 'group', 'place', 'checkin']
        if type not in SUPPORTED_TYPES:
            raise ValueError('Unsupported type "%s". Supported types are %s' % (type, ', '.join(SUPPORTED_TYPES)))

        options = dict({
            'q': term,
            'type': type,
        }, **options)

        response = self._query('GET', 'search', options, page)

        return response

    def batch(self, requests):
        """
        Make a batch request.

        :param requests: A list of dictionaries with keys 'method', 'relative_url' and optionally 'body'.

        Yields a list of responses and/or FacebookError, GraphAPI.HTTPError instances.
        """
        responses = self.post(
            batch = json.dumps(requests)
        )

        for response, request in zip(responses, requests):

            # Facilitate for empty Graph API responses.
            #
            # https://github.com/jgorset/facepy/pull/30
            if not response:
                yield None
                continue

            data = self._parse(response['body'])

            if isinstance(data, Exception):
                data.request = request

                yield data
                continue

            yield data

    def fql(self, query):
        """
        Use FQL to powerfully extract data from Facebook.

        :param query: A FQL query or FQL multiquery ({'query_name': "query",...})

        See `Facebook's FQL documentation <http://developers.facebook.com/docs/reference/fql/>`_
        for an exhaustive list of details.
        """
        return self._query('GET', 'fql?%s' % urlencode({'q': query}))

    def _query(self, method, path, data=None, page=False):
        """
        Fetch an object from the Graph API and parse the output, returning a tuple where the first item
        is the object yielded by the Graph API and the second is the URL for the next page of results, or
        ``None`` if results have been exhausted.

        :param method: A string describing the HTTP method.
        :param url: A string describing the URL.
        :param data: A dictionary of HTTP GET parameters (for GET requests) or POST data (for POST requests).
        :param page: A boolean describing whether to return an iterator that iterates over each page of results.
        """
        data = data or {}

        def load(method, url, data):
            if method in ['GET', 'DELETE']:

                try:
                    response = self.session.request(method, url, params=data, allow_redirects=True)
                except requests.RequestException as exception:
                    raise self.HTTPError(exception.message)


            if method in ['POST', 'PUT']:
                files = {}

                for key in data:
                    if hasattr(data[key], 'read'):
                        files[key] = data[key]

                for key in files:
                    data.pop(key)

                try:
                    response = self.session.request(method, url, data=data, files=files)
                except requests.RequestException as exception:
                    raise self.HTTPError(exception.message)

            result = self._parse(response.content)

            try:
                next_url = result['paging']['next']
            except (KeyError, TypeError):
                next_url = None

            return result, next_url

        def paginate(method, url, data):
            while url:
                result, url = load(method, url, data)

                # Reset pagination parameters.
                for key in ['offset', 'until', 'since']:
                    try:
                        del data[key]
                    except KeyError:
                        pass

                yield result

        # Convert option lists to comma-separated values.
        for key in data:
            if (isinstance(data[key], list) or isinstance(data[key], tuple) or isinstance(data[key], set)) \
                and all([isinstance(item, basestring) for item in data[key]]):
                data[key] = ','.join(data[key])

        url = '%s/%s' % (self.url, path)

        if self.oauth_token:
            data['access_token'] = self.oauth_token

        if page:
            return paginate(method, url, data)
        else:
            return load(method, url, data)[0]

    def _parse(self, data):
        """
        Parse the response from Facebook's Graph API.

        :param data: A string describing the Graph API's response.
        """

        try:
            data = json.loads(data)
        except ValueError:
            return data

        # Facebook's Graph API sometimes responds with 'true' or 'false'. Facebook offers no documentation
        # as to the prerequisites for this type of response, though it seems that it responds with 'true'
        # when objects are successfully deleted and 'false' upon attempting to delete or access an item that
        # one does not have access to.
        #
        # For example, the API would respond with 'false' upon attempting to query a feed item without having
        # the 'read_stream' extended permission. If you were to query the entire feed, however, it would respond
        # with an empty list instead.
        #
        # Genius.
        #
        # We'll handle this discrepancy as gracefully as we can by implementing logic to deal with this behavior
        # in the high-level access functions (get, post, delete etc.).
        if type(data) is dict:
            if 'error' in data:
                error = data['error']

                if error.get('type') == "OAuthException":
                    exception = OAuthError
                else:
                    exception = FacebookError

                return exception(
                    error.get('message'),
                    error.get('code', None)
                )

            # Facebook occasionally reports errors in its legacy error format.
            if 'error_msg' in data:
                return FacebookError(
                    data.get('error_msg'),
                    data.get('error_code', None)
                )

        return data
