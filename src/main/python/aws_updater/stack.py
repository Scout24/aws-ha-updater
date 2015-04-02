import urllib2
import json

import boto.cloudformation
import boto.ec2
import boto.ec2.elb
import boto.ec2.autoscale
import boto.s3.connection


from aws_updater.utils import timed
from aws_updater.asg import ASGUpdater
from aws_updater import describe_stack, get_all_autoscaling_groups, wait_for_action_to_complete
from aws_updater.exception import *

class StackUpdater(object):

    def __init__(self, stack_name, region, observer_callback=None, timeout_in_seconds=None):
        self.stack_name = stack_name
        self.cfn_conn = boto.cloudformation.connect_to_region(region)
        self.as_conn = boto.ec2.autoscale.connect_to_region(region)
        self.ec2_conn = boto.ec2.connect_to_region(region)
        self.elb_conn = boto.ec2.elb.connect_to_region(region)
        self.s3_conn = boto.s3.connection.S3Connection
        self.timeout_in_seconds = timeout_in_seconds

        dummy_observer_callback = lambda event: None
        self.observer_callback = observer_callback or dummy_observer_callback

    def get_all_asgs_from_stack(self):
        stack = describe_stack(self.cfn_conn, self.stack_name)
        if not stack:
            raise Exception("no stack with name '%s' found" % self.stack_name)

        return get_all_autoscaling_groups(self.as_conn, stack)

    @timed
    def update_asgs(self):
        for asg in self.get_all_asgs_from_stack():
            print "updating asg '%s'" % asg.name
            ASGUpdater(asg,
                       self.as_conn,
                       self.ec2_conn,
                       self.elb_conn,
                       self.observer_callback,
                       timeout_in_seconds=self.timeout_in_seconds).update()

    @staticmethod
    def get_parameters_from_list(parameters):
        result = {}
        for parameter in parameters:
            key, value = parameter.split("=", 1)
            result[key] = value
        return result

    def get_file_from_bucket(self, bucketname, filename):
        bucket = self.s3_conn.get_bucket(bucketname)
        file_key = bucket.get_key(filename)
        return file_key.get_contents_as_string()

    def get_template(self, template_filename):
        if template_filename.startswith("s3"):
            try:
                urlparts = template_filename.split('/')
                bucketname = urlparts[2]
                filename = '/'.join(urlparts[3:])
                template = self.get_file_from_bucket(bucketname, filename)
            except boto.exception.BotoServerError, e:
                raise BucketNotAccessibleException("cannot get template_file: {0}, caused by: {1}".format(template_filename, e))
        else:
            with open(template_filename) as template_file:
                template = "".join(template_file.readlines())

        try:
            print "validating template %s" % template_filename
            self.cfn_conn.validate_template(template)
        except boto.exception.BotoServerError, e:
            raise Exception("cannot validate template {0}, caused by: {1}".format(template_filename, e))
        return template

    def update_stack(self, stack_parameters, template_filename=None, lenient_lookback=5, action_timeout=300,
                     warmup_seconds=25):
        if template_filename:
            template = get_template(template_filename)
        else:
            template = None

        stack = describe_stack(self.cfn_conn, self.stack_name)
        if stack:
            action = self.cfn_conn.update_stack
            print "updating running stack"
        else:
            action = self.cfn_conn.create_stack
            print "creating stack"
        if not stack and not template:
            raise Exception("cannot create stack without template")
        if not template:
            template = "".join(
                stack.get_template().get("GetTemplateResponse", {}).get("GetTemplateResult", {}).get("TemplateBody", []))
        given = self.get_parameters_from_list(stack_parameters)
        current = {}
        for p in stack.parameters:
            current[p.key] = p.value
        current.update(given)
        print "parameters"
        for key, value in current.iteritems():
            print "%20s: %s" % (key, value)
        print

        try:
            action(self.stack_name, template_body=template, parameters=[item for item in current.iteritems()],
                            capabilities=['CAPABILITY_IAM'])
        except boto.exception.BotoServerError, e:
            error = json.loads(e.body).get("Error", "{}")
            if error.get("Message") == "No updates are to be performed.":
                print "nothing to do, everything fine :o)"
            else:
                raise Exception("[ERROR] %(Code)20s: %(Message)s" % error)
        except BaseException, e:
            raise Exception("[ERROR] something went horribly wrong: %s" % e)

        wait_for_action_to_complete(self.cfn_conn, self.stack_name, warmup_seconds, lenient_lookback, action_timeout)
