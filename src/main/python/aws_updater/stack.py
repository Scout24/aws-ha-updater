import boto.cloudformation
import boto.ec2
import boto.ec2.elb
import boto.ec2.autoscale

from aws_updater.utils import timed

from aws_updater.asg import ASGUpdater
from aws_updater import describe_stack, get_all_autoscaling_groups


class StackUpdater(object):

    def __init__(self, stack_name, region, observer_callback=None):
        self.stack_name = stack_name
        self.cfn_conn = boto.cloudformation.connect_to_region(region)
        self.as_conn = boto.ec2.autoscale.connect_to_region(region)
        self.ec2_conn = boto.ec2.connect_to_region(region)
        self.elb_conn = boto.ec2.elb.connect_to_region(region)

        if not observer_callback:
            self.observer_callback = self.noop_observer_callback
        else:
            self.observer_callback = observer_callback

    def noop_observer_callback(self):
        pass

    def get_all_asgs_from_stack(self):
        stack = describe_stack(self.cfn_conn, self.stack_name)
        if not stack:
            raise Exception("no stack with name '%s' found" % self.stack_name)

        return get_all_autoscaling_groups(self.as_conn, stack)

    @timed
    def update(self):
        for asg in self.get_all_asgs_from_stack():
            print "updating asg '%s'" % asg.name
            ASGUpdater(asg, self.as_conn, self.ec2_conn, self.elb_conn, self.observer_callback).update()
