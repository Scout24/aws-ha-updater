from boto.sqs.message import Message
from aws_updater.utils import get_logger
from boto import sqs
import logging
import datetime


class SqsQueue(object):

    def __init__(self, region="eu-west-1", queue_name="is24-cfn-custom-resources"):
        self.logger = get_logger()
        logging.getLogger('boto').setLevel(logging.INFO)

        self.conn = sqs.connect_to_region(region)
        self.queue = self.conn.get_queue(queue_name)
        assert self.queue, "Could not get a queue for queue name: {0} in {1}".format(queue_name, region)

    def get_attributes(self):
        return self.conn.get_queue_attributes(self.queue)

    def get_messages(self):
        return self.queue.get_messages(visibility_timeout=60, num_messages=10, wait_time_seconds=20)

    def delete_message(self, message):
        return self.queue.delete_message(message)

    def put_message(self, message_body):
        message = Message()
        message.set_body(message_body)

        self.queue.write(message)

    def get_length(self):
        return self.queue.count()

if __name__ == "__main__":
    queue = SqsQueue()
    queue.put_message("Test {0}".format(datetime.datetime.now()))
    queue.put_message("Test {0}".format(datetime.datetime.now()))

    print "{0} messages in the queue!".format(queue.get_length())
    while True:
        messages = queue.get_messages()
        print "Got {0} messages".format(len(messages))
        if messages:
            for message in messages:
                print vars(message)
                queue.delete_message(message)
        else:
            print "Nothing in the queue"