#!/usr/bin/python
# -*- encoding: utf-8 -*-

# customize for your authorization needs

import flask
import logging
import os
import requests

from decorator import decorator

log = logging.getLogger(__name__)


assert os.getenv('OS_TOKEN', None), 'Please export openstack OS_TOKEN'
assert os.getenv('OS_AUTH_URL', None), 'Please export openstack OS_AUTH_URL'


# auth implementation

def _check_auth(token):
    '''This function is called to check if a token is valid.'''
    # log.info('check_auth {} {}'.format(username, password))
    # TODO
    url = '{}/auth/tokens'.format(os.environ.get('OS_AUTH_URL'))
    headers = {'X-Auth-Token': os.environ.get('OS_TOKEN'),
               'X-Subject-Token': token}
    token_info = requests.get(url, headers=headers).json()
    if 'token' not in token_info:
        log.debug(token_info)
        return False

    url = '{}/auth/projects'.format(os.environ.get('OS_AUTH_URL'))
    headers = {'X-Auth-Token': token}
    project_info = requests.get(url, headers=headers).json()
    if 'projects' not in project_info:
        log.debug(project_info)
        return False

    return True


def _authenticate():
    '''Sends a 401 response that enables basic auth'''
    return flask.Response('You have to provide api key', 401,
                          {'WWW-Authenticate':
                           'API key is missing or invalid'})


@decorator
def authorization_check(f, *args, **kwargs):
    '''wrap functions for authorization'''
    auth = flask.request.headers['Api-Key']
    # log.debug('authorization_check auth {}'.format(auth))
    if not auth or not _check_auth(auth):
        return _authenticate()
    return f(*args, **kwargs)