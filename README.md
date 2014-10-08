aws-ha-updater
==============

Prerequisites:

- python 2.6+ (but not python3)

- boto SDK

- AWS credentials (e.g. $HOME/.boto file)

- AWS resources managed via CloudFormation

- ASGs have NO UpdatePolicy (we implement our own here)


Stack Update
------------

- validate template file when given

- create stack when needed

- update stack and wait for action to complete

- when successfull: update asgs


ASG Update
----------

- suspend all autoscaling processes

- double ASG sizes

- wait for ASG to launch new instances

- wait for instances to be "InService" according to ELB

    - when successfull: terminate the old instances

    - when timeout occured: terminate the new instances

- reset ASG sizes

- resume all processes (when timeout: disable Autoscaling Processes)

