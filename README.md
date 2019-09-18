# job
Job runner with logging

[![Build Status](https://dev.azure.com/wadecarpenter/jobrunner/_apis/build/status/wwade.jobrunner?branchName=master)](https://dev.azure.com/wadecarpenter/jobrunner/_build/latest?definitionId=1&branchName=master)

## Installation
Install system-wide:
```
pip install git+https://github.com/wwade/jobrunner.git
```
Install just for the current user:
```
pip install --user git+https://github.com/wwade/jobrunner.git
```

## Uninstallation
```
pip uninstall jobrunner
```

## Examples
* Run `sleep 5` in the background
```
$ job sleep 5
```
* Run `ls` when the last job finishes and it passed (exit code 0)
```
$ job -B. ls
```
* Run `ls` when last job finishes (pass / fail)
```
$ job -b. ls
```
* Monitor job execution
```
$ job -W
Sat Aug 10, 2019 20:48:23  No jobs running, load: 0/0/0
```
* Retry a job
```
$ job --retry ls
```

### Query Examples

**NOTE** `.` is available as an alias to the most recently executed job (as in the Examples above).

* View recently executed job log file
```
$ job ls
$ view `job`   # Opens the output from ls using "view"
```
* View two most recently executed
```
$ job echo 1
$ job echo 2
$ view `job -n0 -n1`  
```
* Query by job name
```
$ job echo foo
$ job echo bar
$ view `job -g foo`
```
* Show job info by name
```
$ job ls
$ job -s ls
```

## Configuration
The default configuration file location is `~/.config/jobrc`, but can be
overwritten using the --rc-file option.

### Sample rcfile:
```
[mail]
program = mail
domain = example.com
```
