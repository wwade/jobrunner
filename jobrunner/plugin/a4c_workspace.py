from __future__ import absolute_import, division, print_function
import os
import os.path
import re


def workspaceIdentity():
    chroot = os.environ.get('A4_CHROOT', '/')
    if chroot and chroot != '/':
        return os.path.basename(chroot)
    try:
        with file('/p4conf') as fp:
            confLines = [l.strip().split('=') for l in fp.readlines()]
        p4conf = {k: v for k, v in confLines}
    except IOError:
        p4conf = {}
    p4Client = p4conf.get('P4CLIENT')
    containerHostname = os.environ.get('HOSTNAME')
    if p4Client:
        return 'a4c-' + p4conf.get('P4CLIENT')
    elif p4conf and containerHostname:
        return 'a4c-' + re.sub(r'\.sjc.aris.*\.com$', '', containerHostname)
    else:
        return None
