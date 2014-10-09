#!/usr/bin/env python
import boto
import aws_updater
import time
import argparse

from aws_updater.stack import StackUpdater
from aws_updater.asg import ASGUpdater


def read_teststack_template():
    content = ""
    with open("../resources/teststack.json") as file:
        for line in file:
            content += line
    return content

parser = argparse.ArgumentParser()
parser.add_argument("subnet", help="Subnet ID", type=str)
parser.add_argument("az", help="Availability Zone", type=str)
parser.add_argument("vpc", help="VPC ID", type=str)
parser.add_argument("--region", help="Region", default="eu-west-1", type=str)
args = parser.parse_args()

# constants
stack_name = "teststack"
stack_template = read_teststack_template()
region = args.region
subnet = args.subnet
vpc = args.vpc
az = args.az
image_id_mapping = {"ami-892fe1fe": "ami-748e2903",
                    "ami-748e2903": "ami-892fe1fe"}

cfn_conn = boto.cloudformation.connect_to_region(region)
as_conn = boto.ec2.autoscale.connect_to_region(region)


def sizing_info(asg):
    return "asg: {0}, min_size: {1}, max_size {2}, desired_capacity: {2}".format(asg.name, asg.min_size, asg.max_size,
                                                                                 asg.desired_capacity)


def get_image_id(asg):
    launch_config = as_conn.get_all_launch_configurations(names=[asg.launch_config_name])[0]
    image_id = launch_config.image_id
    return image_id


def get_next_ami_id(asg):
    return image_id_mapping[get_image_id(asg)]


def get_asg():
    stack = aws_updater.describe_stack(cfn_conn, stack_name)
    autoscaling_groups = aws_updater.get_all_autoscaling_groups(as_conn, stack)
    assert len(autoscaling_groups) == 1
    return autoscaling_groups[0]


def test_no_update():
    def callback(event):
        print event
        if event == ASGUpdater.SCALE_OUT_COMPLETED:
            raise Exception("No update --> no scaleout!")

    # action plan
    asg_before = get_asg()
    print "Before: " + sizing_info(asg_before)
    StackUpdater(stack_name, region, observer_callback=callback).update()
    asg_after = get_asg()
    print "After: " + sizing_info(asg_after)

    assert asg_before.min_size == asg_after.min_size, "ASG min_size shouldn't have changed"
    assert asg_before.max_size == asg_after.max_size, "ASG max_size shouldn't have changed"
    assert asg_before.desired_capacity == asg_after.desired_capacity, "ASG desired_capacity shouldn't have changed"

    assert len(asg_after.suspended_processes) == 0


def test_update():
    def callback(event):
        print event
        if event == ASGUpdater.SCALE_OUT_COMPLETED:
            asg = get_asg()
            print "ASG sizing after scale_out: " + sizing_info(asg)

            #TODO: add nice error messages
            #TODO: test more precisely
            assert asg.min_size > asg_before.min_size, "ASG min_size should be bigger than before scale_out"
            assert asg.max_size > asg_before.max_size, "ASG max_size should be bigger than before scale_out"
            assert asg.desired_capacity > asg_before.desired_capacity, \
                "ASG desired_capacity should be bigger than before scale_out"

    # action plan
    asg_before = get_asg()
    print "Before: " + sizing_info(asg_before)
    desired_ami_id = get_next_ami_id(asg_before)
    parameters = [
        ("amiID", desired_ami_id),
        ("az", az),
        ("subnetID", subnet),
        ("vpcID", vpc)]
    cfn_conn.update_stack(stack_name, stack_template, parameters=parameters)
    assert aws_updater.wait_for_action_to_complete(cfn_conn,stack_name, 25, 5, 300) == 0

    StackUpdater(stack_name, region, observer_callback=callback).update()
    asg_after = get_asg()
    print "ASG sizing after update: " + sizing_info(asg_after)

    assert asg_before.min_size == asg_after.min_size
    assert asg_before.max_size == asg_after.max_size
    assert asg_before.desired_capacity == asg_after.desired_capacity

    assert len(asg_after.suspended_processes) == 0, "All processes must be resumed after Stackupdater run"

    # terminate instances is async, we need a bit of time to wait here
    # TODO: find something better
    time.sleep(10)

    for instance in asg_after.instances:
        if instance.lifecycle_state in ASGUpdater.RUNNING_LIFECYCLE_STATES:
            print("Found instance: {0} in state: {1}".format(instance.instance_id, instance.lifecycle_state))
            assert instance.launch_config_name == asg_after.launch_config_name, \
                "Instance {0} has launch-config {1} but should have {2}".format(instance.instance_id,
                                                                                instance.launch_config_name,
                                                                                asg_after.launch_config_name)


print("Testing stackupdater doing nothing if there is nothing to do:")
test_no_update()
print("Testing stackupdater updates all instances to match the new lc:")
test_update()
