from __future__ import absolute_import

from jobrunner.config import RC_FILE_HELP


def binDescriptionWithStandardFooter(desc):
    return """{desc}


Configuration:
    The default configuration file location is `~/.config/jobrc`, but can be
    overwritten using the --rc-file option.

{rcfile}
""".format(desc=desc.strip(), rcfile=RC_FILE_HELP)
