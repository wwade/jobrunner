from __future__ import absolute_import, division, print_function

import os


def addArgumentParserBaseFlags(parser, logfileName):
    '''
    Creates a Base argument parser, which should be used for all
    scripts included with jobrunner.
    Provides common flags for config file overrides, etc.

    Provides ALL flags required by the Config class.
    '''
    parser.add_argument(
        "-v",
        dest="verbose",
        help="Increase verbosity (multiple times for more verbose)",
        action="append_const",
        const=1)
    parser.add_argument(
        "-d",
        "--state-dir",
        dest='stateDir',
        metavar="DIR",
        help="Specify state directory (default='%(default)s')",
        default=os.getenv('JOBRUNNER_STATE_DIR', "~/.local/share/jobDb"))
    parser.add_argument("--rc-file", dest="rcFile",
                        help="Specify path to rc-file (default=\"%(default)s\")",
                        default="~/.config/jobrc")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="enable debug output to <state-dir>/log/%s.log" % logfileName)
    parser.add_argument("--debugLocking", dest="debugLevel", action="append_const",
                        const="lock", help="Debug database locking")


def baseParsedArgsToArgList(argv, args):
    argList = []
    if args.verbose:
        argList.append('-v')
    if '--state-dir' in argv or '-d' in argv:
        argList.extend(['--state-dir', args.stateDir])
    if '--rc-file' in argv:
        argList.extend(['--rc-file', args.rcFile])
    if args.debug:
        argList.append('--debug')
    if args.debugLevel:
        argList.append('--debugLocking')

    return argList
