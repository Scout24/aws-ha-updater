#!/usr/bin/env python
from datetime import datetime
import json
import re
import time

SUCCESSFUL_STATES_COMPLETE = (
    "CREATE_COMPLETE", "UPDATE_COMPLETE", "DELETE_COMPLETE")


def format_epoch(epoch):
    return time.asctime(time.gmtime(epoch))


def get_event_epoch(event):
    td = event.timestamp - datetime.utcfromtimestamp(0)
    return td.seconds + td.days * 24 * 3600


def search_for_event(stack, younger_than, filter_fun):
    if not stack:
        return None
    for event in stack.describe_events():
        if filter_fun(event):
            event_epoch = get_event_epoch(event)
            if event_epoch > younger_than:
                return event
    return None


def dump_new_events(stack, younger_than):
    if not stack:
        return None

    for event in stack.describe_events():
        event_epoch = get_event_epoch(event)
        if event_epoch > younger_than:
            dump_event(event, oneline=True)
            younger_than = event_epoch
    return younger_than


def describe_stack(connection, stack_name):
    try:
        for stack in connection.describe_stacks(stack_name):
            return stack
    except Exception:
        return None


def get_all_autoscaling_groups(as_conn, stack):
    asg_resources = []
    for resource in stack.describe_resources():
        if resource.resource_type == "AWS::AutoScaling::AutoScalingGroup":
            asg_resources.append(resource.physical_resource_id)
    return as_conn.get_all_groups(asg_resources)


def dump(d, header=None, message=None, indent=0, exclude_keys=[]):
    def dump_line(k, v):
        sep = ": " if k else "  "
        print "%s%30s%s%s" % ("    " * indent, k, sep, v)
    if not message:
        message = "#" * 40
    if header:
        dump_line(header, message)
    t = type(d)
    if not hasattr(d, "iteritems"):
        d = vars(d)
    for k, v in d.iteritems():
        if k in exclude_keys:
            continue
        if type(v) is unicode:  # yukk
            v = v.strip()
        if not v:
            continue
        try:
            v = json.loads(v)
            v = json.dumps(v, indent=4)
        except Exception:
            pass
        v = str(v)
        first_line = True
        for line in v.splitlines():
            if first_line:
                first_line = False
                dump_line(k, line)
            else:
                dump_line("", line)
    dump_line("python type", t)
    print


def dump_stack(d):
    dump(d, "stack")


def dump_event(d, message=None, indent=1, oneline=False):
    if oneline:
        reason = d.resource_status_reason
        reason = reason if reason else ""
        rt = re.sub(".*::", "", d.resource_type)
        print "%40s  %-10s %-20s  %s" % (d.resource_status, d.logical_resource_id, rt, reason)
    else:
        dump(d, "event", message, indent, [
            "stack_id", "connection", "stack_name", "physical_resource_id"])


def dump_resource(d):
    dump(d, "resource", 1, ["stack_id", "connection", "stack_name"])


def wait_for_start_event(connection, stack_name, action_timeout, lenient_look_back):
    started = time.time()
    check_until = started + action_timeout
    print "waiting for max. %i seconds for an action to start on %s" % (action_timeout, stack_name)
    # print "        now: %s" % format_epoch(started)
    # print "check until: %s" % format_epoch(check_until)
    print
    younger_than = started - lenient_look_back

    stack = None
    last = started
    while time.time() < check_until:
        # print "checking events for start event on stack %s" % stack_name
        last = dump_new_events(stack, last)
        if not stack:
            stack = describe_stack(connection, stack_name)
        if not stack:
            print "stack does not exist yet"
        start_event = search_for_event(
            stack,
            younger_than,
            lambda event: event.resource_type == "AWS::CloudFormation::Stack" and event.resource_status.endswith("_PROGRESS")
        )
        if start_event:
            return (stack, start_event)
        time.sleep(1)
    return (stack, None)


def wait_for_end_event(connection, stack, younger_than, action_timeout):
    started = time.time()
    check_until = started + action_timeout
    print "waiting for max. %i seconds for an event to occur on %s" % (action_timeout, stack.stack_name)
    print

    last = started
    while time.time() < check_until:
        new_last = dump_new_events(stack, last)
        if new_last != last:
            last = new_last
            check_until = last + action_timeout
        end_event = search_for_event(
            stack,
            younger_than,
            lambda event: event.resource_type == "AWS::CloudFormation::Stack" and event.resource_status.endswith("_COMPLETE") and event.logical_resource_id == stack.stack_name
        )
        if end_event:
            return (stack, end_event)
        time.sleep(1)
    return (stack, None)


def wait_for_action_to_complete(cloudformation_conn, stack_name, warmup_seconds, lenient_look_back, action_timeout):
    (stack, start_event) = wait_for_start_event(
        cloudformation_conn, stack_name, warmup_seconds, lenient_look_back)
    if not start_event:
        print "no start event encountered"
        return 2
    dump_event(start_event, message="ACTION STARTED")
    print

    (stack, end_event) = wait_for_end_event(
        cloudformation_conn, stack, get_event_epoch(start_event), action_timeout)
    print
    if not end_event:
        print "no end event encountered within %i seconds" % action_timeout
        return 3
    dump_event(end_event, message="ACTION FINISHED")

    status = end_event.resource_status
    print status
    if status in SUCCESSFUL_STATES_COMPLETE:
        return 0
    else:
        return 1
