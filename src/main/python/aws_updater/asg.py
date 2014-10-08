from __future__ import print_function
import time


class UnhealthyInstanceFound(Exception):
    pass


class TimeoutException(Exception):
    pass


class RolledBackException(Exception):
    pass


class ASGUpdater(object):
    RUNNING_LIFECYCLE_STATES = ("Pending", "InService", "Rebooting")
    SCALE_OUT_COMPLETED = "SCALE_OUT_COMPLETED"


    def __init__(self, asg, as_conn, ec2_conn, elb_conn, observer_callback=None):
        self.asg = asg
        self.as_conn = as_conn
        self.ec2_conn = ec2_conn
        self.elb_conn = elb_conn
        self.original_desired_capacity = None
        self.original_min_size = None
        self.original_max_size = None
        self.observer_callback = observer_callback

    def update(self):
        if self.needs_update():
            try:
                self.scale_out()
                self.wait_for_scale_out_complete()
                self.commit_update()
            except Exception as e:
                print("Problem while updating ASG {0}.\nRolling back now.".format(self.asg.name))
                self.rollback()
                raise RolledBackException("Rolled back because of {0}".format(e))

    def wait_for_scale_out_complete(self, needed_nr_of_uptodate_instances=None):
        if not needed_nr_of_uptodate_instances:
            needed_nr_of_uptodate_instances = self.count_running_instances()
        print("waiting for %i instances to have '%s' and be 'InService'" % (needed_nr_of_uptodate_instances, self.asg.launch_config_name))
        start = time.time()
        wait_until = start + 600  # TODO make configurable
        while True:
            self.asg = self.as_conn.get_all_groups(names=[self.asg.name])[0]    # TODO refactor
            instances = self.get_instances_views()

            nr_of_uptodate_instances = self.get_nr_of_uptodate_instances(instances)
            self.print_instances(instances)
            if nr_of_uptodate_instances >= needed_nr_of_uptodate_instances:
                break
            print("%i instances uptodate, %i needed... waiting for %i seconds" % (nr_of_uptodate_instances, needed_nr_of_uptodate_instances, wait_until - time.time()))
            if time.time() > wait_until:
                raise TimeoutException("Timed out waiting for instances in ASG {0} to become healthy.".format(self.asg.name))
            time.sleep(1)

    def get_instances_views(self):
        ids = [instance.instance_id for instance in self.asg.instances]

        result = {}
        for i in self.as_conn.get_all_autoscaling_instances(instance_ids=ids):
            result.setdefault(i.instance_id, {})["asg"] = i
        for i in self.ec2_conn.get_only_instances(instance_ids=ids):
            result.setdefault(i.id, {})["ec2"] = i
        for elb in self.elb_conn.get_all_load_balancers(self.asg.load_balancers):
            for i in self.elb_conn.describe_instance_health(elb.name):
                result.setdefault(i.instance_id, {})["elb"] = i

        return result

    def print_instances(self, instances):
        for id, views in instances.iteritems():
            print("%15s, %10s, %20s, %s" % (id,
                                            getattr(views.get("ec2", {}), "image_id", "?"),
                                            getattr(views.get("asg", {}), "launch_config_name", "?"),
                                            getattr(views.get("elb", {}), "state", "?")
                                            ))

    def get_nr_of_uptodate_instances(self, instances=None):
        if not instances:
            instances = self.get_instances_views()
        nr_of_uptodate_instances = 0
        for id, views in instances.iteritems():
            if getattr(views.get("asg", {}), "launch_config_name", None) == self.asg.launch_config_name:
                if getattr(views.get("elb", {}), "state", None) == "InService":  # TODO use constant here
                    nr_of_uptodate_instances += 1
        print()

        return nr_of_uptodate_instances

    def needs_update(self):
        return self.get_nr_of_uptodate_instances() < self.count_running_instances()

    def count_running_instances(self):
        count = 0
        for instance in self.asg.instances:
            if instance.lifecycle_state in self.RUNNING_LIFECYCLE_STATES:
                count += 1
        return count

    def scale_out(self):
        asg_processes_to_keep = ['Launch', 'Terminate', 'HealthCheck', 'AddToLoadBalancer']
        self.asg.suspend_processes()
        self.asg.resume_processes(asg_processes_to_keep)
        print("Disabled autoscaling processes on {0} (except for {1})".format(self.asg.name, asg_processes_to_keep))

        self.original_desired_capacity = self.asg.desired_capacity
        self.original_min_size = self.asg.min_size
        self.original_max_size = self.asg.max_size

        nr_running_instances = self.count_running_instances()
        self.asg.max_size = self.original_max_size + nr_running_instances
        self.asg.min_size = self.original_min_size + nr_running_instances
        self.asg.desired_capacity = self.original_desired_capacity + nr_running_instances

        print("Temporarily updating ASG parameters:\n\tmax_size: {0} -> {1}\n\tmin_size: {2} -> {3}\n\tdesired_capacity: {4} -> {5}".format(
            self.original_max_size, self.asg.max_size,
            self.original_min_size, self.asg.min_size,
            self.original_desired_capacity, self.asg.desired_capacity))

        self.asg.update()
        self.observer_callback(self.SCALE_OUT_COMPLETED)

    def commit_update(self):
        """
        * Removes instances from ASG which do not belong to the *new* launch configuration
        * Restores the old ASG parameters
        * Resumes all ASG processes
        """
        instances_with_old_launch_config = [instance.instance_id for instance in self.asg.instances
                                            if instance and instance.launch_config_name != self.asg.launch_config_name]

        self._terminate_instances(instances_with_old_launch_config)

        self._restore_original_asg_size()

        self.asg.resume_processes()
        print("Resumed all ASG processes on {0}".format(self.asg.name))

    def rollback(self):
        """
        * Removes instances from ASG which are running the *new* AMI
        * Restores the old ASG parameters
        * Marks the ASG as degraded
        """
        instances_with_new_launch_config = [instance.instance_id for instance in self.asg.instances
                                            if instance and instance.launch_config_name == self.asg.launch_config_name]

        self._terminate_instances(instances_with_new_launch_config)

        self._restore_original_asg_size()

    def _restore_original_asg_size(self):
        print("Resetting ASG parameters:\n\tmax_size: {1} -> {0}\n\tmin_size: {3} -> {2}\n\tdesired_capacity: {5} -> {4}".format(
            self.original_max_size, self.asg.max_size,
            self.original_min_size, self.asg.min_size,
            self.original_desired_capacity, self.asg.desired_capacity))

        self.asg.max_size = self.original_max_size
        self.asg.min_size = self.original_min_size
        self.asg.desired_capacity = self.original_desired_capacity

        self.asg.update()

    def _terminate_instances(self, instances):
        if not instances:
            print("No instances to terminate.")
            return
        print("Terminating instances {0}".format(" ".join(instances)))
        self.ec2_conn.terminate_instances(instances)
