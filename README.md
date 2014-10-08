aws-ha-updater
==============

The `aws-ha-updater` allows you to update AWS EC2 stacks in a highly available manner.

## Why another tool?
* Raw CloudFormation would be the preferred solution for rolling out updates, **but** CloudFormation is currently
unable to use the ELB health check to see if an instance with a new launch configuration comes up healthy.
The result is that deployment with CloudFormation is a gamble that might result in a cluster of borked instances,
which is not acceptable for a web company.

* Asgard, the netflix solution to this, is being rewritten and nobody knows for sure when 2.0 will hit the repository.

* The aws-missing-tools repository provides a bash and ruby implementation. We're not comfortable with using bash to 
instrument EC2/CFN, and have not evaluated the ruby variant. This solution is however heavily inspired by the
aws-ha-release script from the missing-tools collection.


## Prerequisites:

- python 2.6+ (but not python3 yet)

- boto SDK

- AWS credentials (e.g. $HOME/.boto file)

- AWS resources managed via CloudFormation

- ASGs have NO UpdatePolicy (we implement our own here)

## Usage
```
    update-stack STACK_NAME [options] [PARAMETER...]

Options:
    --region=STRING            aws region to connect to [default: eu-west-1]
    --template=FILENAME

    --warmup-seconds=INT       Seconds to wait for warmup [default: 25]
    --action-timeout=INT       Seconds to wait for the action to finish [default: 300]
    --lenient_look_back=INT    Seconds to look back for events [default: 5]
```

```
    update-asgs STACK_NAME [options]

Options:
    --region=TEXT   aws region [default: eu-west-1]
```

## Big picture

### `update-stack`

- validate template file when given

- create stack when needed

- update stack and wait for action to complete

- when successful: update asgs


### `update-asgs`

- suspend all autoscaling processes

- double ASG sizes

- wait for ASG to launch new instances

- wait for instances to be "InService" according to ELB

    - when successful: terminate the old instances

    - when timeout occured: terminate the new instances

- reset ASG sizes

- resume all processes (when timeout: disable autoscaling processes)
