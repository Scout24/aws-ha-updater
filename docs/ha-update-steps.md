aws-ha-updater | strategy
=========================

context
-------

- ASG without UpdatePolicy (we will implement one here)

- stack.update() finished with a newly created LaunchConfig

- ASG with n instances "ELB InService"


steps
-----

- suspend_processes()

    * which processes?

- increase ASG sizes to n + 1

    * what about desired_capacity?

- wait for newly launched instance

    * via tag?

    * via missing lc.name?

- wait for "ELB InService" of new instance

    * which timeout?

- resume_processes()

- set ASG sizes to 2 * n

- for every new instance with "ELB InService":

    * decrement ASG size accordingly

    * terminate old instance

