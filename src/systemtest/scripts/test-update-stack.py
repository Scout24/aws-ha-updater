#!/usr/bin/python2.6
import time
import argparse
import logging

import boto

import aws_updater
from aws_updater.stack import StackUpdater
from aws_updater.asg import ASGUpdater


logging.basicConfig(format='%(asctime)s %(levelname)s: %(message)s', datefmt='%d.%m.%Y %H:%M:%S',level=logging.INFO)
logger = logging.getLogger(__name__)

parser = argparse.ArgumentParser()
parser.add_argument("subnet", help="Subnet ID", type=str)
parser.add_argument("az", help="Availability Zone", type=str)
parser.add_argument("vpc", help="VPC ID", type=str)
parser.add_argument("--region", help="Region", default="eu-west-1", type=str)
args = parser.parse_args()

# constants
stack_name = "teststack-" + str(int(time.time()))
region = args.region
subnet = args.subnet
vpc = args.vpc
az = args.az
image_id_mapping = {"ami-892fe1fe": "ami-748e2903",
                    "ami-748e2903": "ami-892fe1fe"}

cfn_conn = boto.cloudformation.connect_to_region(region)
as_conn = boto.ec2.autoscale.connect_to_region(region)


def create_stack():
    parameters = [
        "amiID=ami-748e2903",
        "az=" + az,
        "subnetID=" + subnet,
        "vpcID=" + vpc
    ]
    StackUpdater(stack_name, region).update_stack(parameters, "../resources/teststack.json")
    # to test S3 bucket access
    # StackUpdater(stack_name, region).update_stack(parameters, "s3://is24-cfn-templates/teststack.json")


def update_stack(parameters):
    StackUpdater(stack_name, region).update_stack(parameters)


def delete_stack():
    cfn_conn.delete_stack(stack_name)
    assert aws_updater.wait_for_action_to_complete(cfn_conn,stack_name, 25, 5, 300) == 0, \
        "Stack deletion didn't complete within 300s"


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

def count_running_instances(asg):
    RUNNING_LIFECYCLE_STATES = ("Pending", "InService", "Rebooting")
    count = 0
    for instance in asg.instances:
        if instance.lifecycle_state in RUNNING_LIFECYCLE_STATES:
            count += 1
    return count

def test_no_update():
    def callback(event):
        if event == ASGUpdater.SCALE_OUT_COMPLETED:
            raise Exception("No update --> no scaleout!")

    # action plan
    asg_before = get_asg()
    running_instances_before = count_running_instances(asg_before)
    logger.info("ASG sizing before update: " + sizing_info(asg_before))
    logger.info("Running instances before update: {0}".format(running_instances_before))

    # test asg size directly after creation
    assert asg_before.min_size == 1; "ASG min_size should be equal zu what is configured in teststack.json"
    assert asg_before.max_size == 6; "ASG max_size should be equal zu what is configured in teststack.json"
    assert asg_before.desired_capacity == 3; "ASG desired_capacity should be equal zu what is configured in teststack.json"

    StackUpdater(stack_name, region, observer_callback=callback).update_asgs()

    asg_after = get_asg()
    running_instances_after = count_running_instances(asg_after)
    logger.info("ASG sizing after update: " + sizing_info(asg_after))
    logger.info("Running instances after update: {0}".format(running_instances_after))

    assert asg_before.min_size == asg_after.min_size, "ASG min_size shouldn't have changed"
    assert asg_before.max_size == asg_after.max_size, "ASG max_size shouldn't have changed"
    assert asg_before.desired_capacity == asg_after.desired_capacity, "ASG desired_capacity shouldn't have changed"
    assert running_instances_before == running_instances_after, "Number of running instances shouldn't have changed"

    assert len(asg_after.suspended_processes) == 0


def test_update():
    def callback(event):
        if event == ASGUpdater.SCALE_OUT_COMPLETED:
            asg = get_asg()
            print "ASG sizing after scale_out: " + sizing_info(asg)

            #TODO: test more precisely
            assert asg.min_size > asg_before.min_size, "ASG min_size should be bigger than before scale_out"
            assert asg.max_size > asg_before.max_size, "ASG max_size should be bigger than before scale_out"
            assert asg.desired_capacity > asg_before.desired_capacity, \
                "ASG desired_capacity should be bigger than before scale_out"

    # action plan
    asg_before = get_asg()
    logger.info("ASG sizing before update: " + sizing_info(asg_before))

    desired_ami_id = get_next_ami_id(asg_before)
    parameters = [
        "amiID=" + desired_ami_id,
        "az=" + az,
        "subnetID=" + subnet,
        "vpcID=" + vpc
    ]
    update_stack(parameters)

    StackUpdater(stack_name, region, observer_callback=callback).update_asgs()

    logger.info("Waiting 300s to ensure asg is in consistent state...")
    time.sleep(300)
    asg_after = get_asg()
    logger.info("ASG sizing after update: " + sizing_info(asg_after))

    assert asg_before.min_size == asg_after.min_size, "Min size of ASG shouldn't have changed"
    assert asg_before.max_size == asg_after.max_size, "Max size of ASG shouldn't have changed"
    assert asg_before.desired_capacity == asg_after.desired_capacity, "Desired capacity of ASG shouldn't have changed"

    assert len(asg_after.suspended_processes) == 0, "All processes must be resumed after Stackupdater run"

    # terminate instances is async, we need a bit of time to wait here
    # TODO: find something better
    logger.info("Waiting 300s to ensure old instances are terminated before checking consistency...")
    time.sleep(300)

    print logger.info("Found the following instances: " + str(asg_after.instances))
    for instance in asg_after.instances:
        if instance.lifecycle_state in ASGUpdater.RUNNING_LIFECYCLE_STATES:
            logger.info("Found instance: {0} in state: {1}".format(instance.instance_id, instance.lifecycle_state))
            assert instance.launch_config_name == asg_after.launch_config_name, \
                "Instance {0} has launch-config {1} but should have {2}".format(instance.instance_id,
                                                                                instance.launch_config_name,
                                                                                asg_after.launch_config_name)


logger.info("Creating new stack for this test: {0}".format(stack_name))
create_stack()

logger.info("Waiting 300s to ensure the stack is fully populated before going on")
time.sleep(300)

logger.info("Testing stackupdater doing nothing if there is nothing to do:")
try:
    test_no_update()
    logger.info("Successfully completed test_no_update")
except Exception as e:
    logger.error("test_no_update failed with error: " + str(e))
    logger.exception(e)

logger.info("Testing stackupdater updates all instances to match the new lc:")
try:
    test_update()
    logger.info("Successfully completed test_update")
except Exception as e:
    logger.error("test_update failed with error: " + str(e))
    logger.exception(e)

logger.info("Deleting stack: {0}".format(stack_name))
delete_stack()
