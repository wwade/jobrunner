job
===

Job runner with logging

|Build Status|
|PyPI Release|

Installation
------------

Install system-wide:

.. code:: console

    $ pip install shell-jobrunner

Install just for the current user:

.. code:: console

    $ pip install --user shell-jobrunner

Uninstallation
--------------

.. code:: console

    $ pip uninstall jobrunner

Examples
--------

-  Run ``sleep 5`` in the background

   .. code:: console

       $ job sleep 5

-  Run ``ls`` when the last job finishes and it passed (exit code 0)

   .. code:: console

       $ job -B. ls

-  Run ``ls`` when last job finishes (pass / fail)

   .. code:: console

       $ job -b. ls

-  Monitor job execution

   .. code:: console

       $ job -W
       Sat Aug 10, 2019 20:48:23  No jobs running, load: 0/0/0

-  Retry a job

   .. code:: console

       $ job --retry ls

Query Examples
~~~~~~~~~~~~~~

**NOTE** ``.`` is available as an alias to the most recently executed
job (as in the Examples above).

-  View recently executed job log file

   .. code:: console

       $ job ls
       $ view `job`   # Opens the output from ls using "view"

-  View two most recently executed

   .. code:: console

       $ job echo 1
       $ job echo 2
       $ view `job -n0 -n1`

-  Query by job name

   .. code:: console

       $ job echo foo
       $ job echo bar
       $ view `job -g foo`

-  Show job info by name

   .. code:: console

       $ job ls
       $ job -s ls

Configuration
-------------

| The default configuration file location is ``~/.config/jobrc``, but can be
| overridden using the --rc-file option.

Sample rcfile:
~~~~~~~~~~~~~~

.. code:: aconf

    [mail]
    program = mail
    # For notifications over chat applications (like Google Chat), use chatmail as
    # your mail program instead. "chatmail" must be specified rather than a differently
    # named link to the script, else some options provided to job (such as --rc-file)
    # will not be passed through to it.
    # program = chatmail
    domain = example.com
    [ui]
    watch reminder = full|summary  # default=summary
    [chatmail]
    at all = all|none|no id # default=none
    reuse threads = true|false # default true
    [chatmail.google-chat-userhooks]
    user1 = https://chat.googleapis.com/v1/spaces/...
    [chatmail.google-chat-userids]
    # Retrieve this using your browser inspector on an existing mention of this user.
    # It should show up as "user/some_long_integer" somewhere in the span's metadata.
    user1 = <long integer>

Hacking
-------

Primary workflow
~~~~~~~~~~~~~~~~

It's highly recommend to work inside a virtualenv using ``pipenv``.

Create new virtualenv and install an editable version of ``jobrunner``:

.. code:: console

    pipenv --three install --dev
    pipenv run pip install -e .

Autoformat the code and check linters:

.. code:: console

    pipenv run ./format.sh

Run tests:

.. code:: console

    pipenv run pytest

Run CI checks locally
~~~~~~~~~~~~~~~~~~~~~

| This allows you to run something similar to the azure pipelines locally using docker.
| It will use ``PIP_INDEX_URL`` and / or ``~/.config/pip/pip.conf`` to configure a pypi mirror.
| This will also update ``Pipfile*.lock``.

.. code:: console

    ./test-docker.py [--versions 2.7 3.7 3.8] [--upgrade] [--ignore-unclean]

.. |Build Status| image:: https://dev.azure.com/wadecarpenter/jobrunner/_apis/build/status/wwade.jobrunner%20(azure%20native)?branchName=master
   :target: https://dev.azure.com/wadecarpenter/jobrunner/_build/latest?definitionId=2&branchName=master

.. |PyPI Release| image:: https://badge.fury.io/py/shell-jobrunner.svg
   :target: https://badge.fury.io/py/shell-jobrunner
