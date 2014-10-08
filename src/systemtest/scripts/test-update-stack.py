#!/usr/bin/env python
import boto
import aws_updater

from aws_updater.stack import StackUpdater

def sizing_info(asg):
    return "asg: {0}, min_size: {1}, max_size {2}, desired_capacity: {2}".format(asg.name, asg.min_size, asg.max_size,
                                                                                        asg.desired_capacity)

stack_name = "teststack"
region = "eu-west-1"

cfn_conn = boto.cloudformation.connect_to_region(region)
as_conn = boto.ec2.autoscale.connect_to_region(region)

stack = aws_updater.describe_stack(cfn_conn, stack_name)
autoscaling_groups = aws_updater.get_all_autoscaling_groups(as_conn, stack)

assert len(autoscaling_groups) == 1

asg = autoscaling_groups[0]

min_size = asg.min_size
max_size = asg.max_size
desired_capacity = asg.desired_capacity

print "BEFORE: " + sizing_info(asg)

StackUpdater(stack_name, region).update()


autoscaling_groups = aws_updater.get_all_autoscaling_groups(as_conn, stack)

assert len(autoscaling_groups) == 1

asg = autoscaling_groups[0]

print "AFTER: " + sizing_info(asg)

assert asg.min_size == min_size
assert asg.max_size == max_size
assert asg.desired_capacity == desired_capacity
