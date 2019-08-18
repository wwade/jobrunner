## Intro
Thanks for helping out!  I'll make every effort to respond to PRs in a relateively short time, once the CI has passed, at least.

## Development Environment
### Requirements
- virtualenv >= 16.7.3 `pip install virtualenv` or `pip install --user virtualenv`
### Enivronment
```
$ git clone git@github.com:wwade/jobrunner.git
$ cd jobrunner
$ . testenv
(venv27)$ 
```
### Running Tests
The full CI test suite
```
(venv27)$ tox
```
Individual tests can be executed with `nosetests` or `pytest`.  A coverage report for unit tests can be created by running `./cover.sh` from inside the virtualenv.
To just run unit tests, you can skip the integration tests with `nosetests`:
```
(venv27)$ nosetests -e integration
```

## Guidelines
1. Please try to keep PRs on a single topic.  Generally this means that they'll invlove a "small" number of commits, and that each commit contains the minimal changes for its purpose.
2. Since we don't have `gofmt`, just run `./format.sh` before committing your changes.
3. If you don't hear back on your PR in a "reasonable" time, just send me an email :)
