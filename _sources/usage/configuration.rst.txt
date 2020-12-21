Configuration
=============

:command:`metricq_sink_nsca` retrieves its configuration over the MetricQ network in form of a JSON object.
The configuration defines a set of checks and specifies the host to which results of these check results should be sent.

For the impatient
-----------------

A minimum working configuration looks like this:

.. code-block:: json

    {
        "nsca": {
            "host": "nsca.example.org",
        },
        "checks": {
            "bar": {
                "metrics": [
                    "bar.1",
                    "bar.2"
                ],
                "warning_above": 10.0,
                "critical_above": 15.0,
                "timeout": "1min"
            }
        }
    }

You tell it where to send the check results to (:code:`"nsca.host"`)
and then define for each check a list of metrics whose values are checked for abnormal values,
as given by :literal:`{warning,critical}_above`.
Checks need to be configured as passive checks on the host side,
otherwise reports will be dropped silently by the host.

Full reference
--------------

Top-level configuration
^^^^^^^^^^^^^^^^^^^^^^^

:code:`nsca`
    A dictionary of :ref:`NSCA host settings`.

:code:`checks`
    A dictionary of :ref:`check configurations<Check configuration>` by name.

    Example
        Suppose you have configured a passive check called :literal:`foo` in Centreon/Nagios
        and want to be alerted when values of either of the metrics :literal:`foo.bar` or :literal:`foo.baz`
        drop below a threshold.
        A possible configuration looks like this:

        .. code-block:: json

            {
                "nsca": {
                    "host": "nsca.example.org",
                },
                "checks": {
                    "foo": {
                        "metrics": [
                            "foo.bar",
                            "foo.baz"
                        ],
                        "warning_below": 10.0,
                        "critical_below": 5.0
                    }
                }
            }

:code:`reporting_host`
    Name of the host for which check results are reported, as configured in Nagios/Centreon.

    Default:
        The current hostname returned by :manpage:`gethostname(2)`.

:code:`resend_interval`
    .. _global_resend_interval:

    Global default resend interval (see :ref:`Check configuration/resend_interval<resend_interval>`).

    Default
        :literal:`"3min"`

Check configuration
^^^^^^^^^^^^^^^^^^^

A single check monitors a set of metrics for abnormal behavior.
It continuously consumes new data points for these metrics
and reports and `overall state`: if values of a single metric exceed their :ref:`allowed range<abnormal-ranges>`
or there are no new values after :ref:`a certain time<timeout>`
a state of :literal:`WARNING` or :literal:`CRITICAL` is reported.

:code:`metrics` (list of strings)
    A list of metrics that should be monitored.

    This list is **mandatory** and required to be *non-empty*.


:code:`warning_above`, :code:`warning_below`, :code:`critical_above`, :code:`critical_below` (number)
    .. _abnormal-ranges:

    Range of value which should trigger a :literal:`WARNING` (resp. :literal:`CRITICAL`) status report to be sent.
    We call the intervals :math:`[-∞, \mathtt{warning\_below}) \cup (\mathtt{warning\_above}, ∞]` the *warning range*;
    values within that range trigger a :literal:`WARNING`.
    The *critical range* is defined similarly.

    We require the following, otherwise the configuration is rejected:

    .. math::
        \mathtt{critical\_below}
            ≤ \mathtt{warning\_below}
            < \mathtt{warning\_above}
            ≤ \mathtt{critical\_above}

    A :literal:`WARNING` report is sent if the value of a metric drops below :literal:`warning_below`,
    a :literal:`CRITICAL` report is sent if it drops further below :literal:`critical_below`.
    Metrics exceeding :literal:`warning_above` or :literal:`critical_above` similarly trigger reports.

    Defaults
        * :math:`-∞` (:code:`{warning,critical}_below`)
        * :math:`∞`  (:code:`{warning,critical}_above`)

        You cannot put :math:`±∞` directly into the check configuration.
        Since they are the default anyway, simply omit the relevant key if necessary.

    Important
        Setting any of these values forces incoming messages to be decoded and parsed,
        which adds significant overhead for high-volume metrics.
        Leave all values unset to disable packet processing and only check for timeouts.

    Example
        An example check configuration with all ranges specified:

        .. code-block:: json

            {
                "checks": {
                    "foo": {
                        "metrics": [ "foo.bar", "foo.baz" ],
                        "critical_below":   5.0,
                        "warning_below":   10.0,
                        "warning_above":   95.0,
                        "critical_above": 100.0
                    }
                }
            }

:code:`timeout` (:ref:`duration<Duration>`)
    .. _timeout:

    Send check result of severity :literal:`WARNING` if values arrive apart more than the specified period.
    This monitors two kinds of failure:

    - The network is fully operational, but two consecutive data points for a metric differ by more than :code:`timeout` in their timestamps.
      This might indicate that the source for these metrics is not fully operational.

    - :command:`metricq_sink_nsca` does not receive data points for these metrics for more than the specified duration,
      measured against the local system clock.
      This might happen if a source has crashed, has lost its connection to the network
      or there is another issue along the way that prevents clients from consuming new value for these metrics.

    Default
        Not set; no timeout checks are performed.

    Note
        Timeout checks can be enabled independently from :ref:`value checks<abnormal-ranges>`.
        They do not require incoming messages to be parsed and can safely be enabled for high-volume metrics
        without incurring much overhead.

    Example
        Make sure that :literal:`foo.bar` consistently produces values:

        .. code-block:: json

            {
                "checks": {
                    "foo": {
                        "metrics": ["foo.bar"],
                        "timeout": "1min"
                    }
                }
            }

:code:`ignore` (list of numbers)
    A list of values that are never considered to generate :literal:`WARNING` or :literal:`CRITICAL` reports.

    This is intended to be used for metrics that yield spurious, but fixed values that should be ignored,
    even if they are within an otherwise abnormal range.
    An example would be a faulty measuring device which produces the value :literal:`0.0` on encountering in an internal error,
    but where :literal:`warning_below = 5.0`.

    .. note::

        **Use with care**.
        The implementation essentially only performs a floating-point equality test to filter values.

        If this sounds like a bad idea to you, you are probably right.
        Trust me, this is here because some source cannot be fixed easily.

    Example
        A source computing a `Power factor <https://en.wikipedia.org/wiki/Power_factor>`_
        for an AC electrical power system reports a metric :literal:`ac_system.power_factor`.
        If the power factor is too low, a warning should be generated.
        It might be that the source calculates a power factor of :literal:`0.0` on low draw.
        Since a low power factor on low draw might not be considered a problem,
        ignore the value :literal:`0.0`:

        .. code-block:: json

            {
                "checks": {
                    "low-draw": {
                        "metrics": ["ac_system.power_factor"],
                        "warning_below": 0.8,
                        "ignore": [0.0]
                    }
                }
            }

:code:`resend_interval` (:ref:`duration<Duration>`)
    .. _resend_interval:

    Period of time after which the current state of this check is sent again to the server, even though it might not have changed.
    This is necessary since passive checks are considered to be in an :literal:`UNKNOWN` state by Centreon/Nagios
    if they have not sent a report for a certain time.

    Default
        Inherited from the :ref:`global resend interval<global_resend_interval>`.

:code:`transition_debounce_window` (:ref:`duration<Duration>`)
    If this value is set, :command:`metricq_sink_nsca` tries to reduce the number of spurious :literal:`WARNING` or :literal:`CRITICAL` reports.
    We call this process *"transition debouncing"*.

    If you are experiencing state transitions to :literal:`WARNING` or :literal:`CRITICAL`
    that only last :math:`x` seconds and want to suppress them, set this value to at least :math:`2x` seconds.

    For each metric, a history of its state transitions is kept.
    This configures how far into the past state transitions are kept in each history.
    If the majority of recent state transitions indicate an abnormal state, a report is sent.
    Otherwise it is suppressed.

    Default
        Not set; transitions debouncing is disabled.

    TODO
        This should be called :literal:`transition_history_window`.
        Bug me about it in an issue.

:code:`plugins`
    A dictionary of :ref:`plugin configurations<Plugin configuration>`.
    Keys in this dictionary must match the regex :literal:`[a-z_]+`.


NSCA host settings
^^^^^^^^^^^^^^^^^^

These settings tell the reporter where it should send its check results and how that host is configured.

:code:`host` (`string`)
    Address of the NSCA daemon to which check results are sent.
    See :code:`-H` flag of :code:`send_nsca`.

    Default:
        :literal:`"localhost"`

:code:`port` (`integer`)
    Port of the NSCA daemon to which check results are sent.
    See :code:`-p` flag of :code:`send_nsca`.

    Default:
        :literal:`5667`

:code:`executable` (`string`)
    Path to :code:`send_nsca` executable to use for sending check results.

    Default:
        :literal:`"/usr/sbin/send_nsca"`

:code:`config_file` (`string`)
    Path to :code:`send_nsca` configuration file.
    See :code:`-c` flag of :code:`send_nsca`

    Default:
        :literal:`"/etc/nsca/send_nsca.cfg"`

Plugin configuration
^^^^^^^^^^^^^^^^^^^^

:code:`file` (string)
    File system path to plugin implementation (a `.py` file).

    This key is **mandatory**.
    Plugin configurations without it are rejected.

:code:`config` (dictionary)
    An arbitrary JSON object containing a plugin-specific configuration.

Duration
^^^^^^^^

All durations in this configuration are *strings* in the form of :samp:`"{value} [{unit}]"`.
The :samp:`{value}` is an integer or (decimal) floating point literal, the unit is one of

* :literal:`d`/:literal:`days`
* :literal:`h`/:literal:`hours`
* :literal:`min`/:literal:`minutes`
* :literal:`s`/:literal:`seconds`
* :literal:`ms`/:literal:`milliseconds`
* :literal:`us`/:literal:`μs`/:literal:`microseconds`,
* :literal:`ns`/:literal:`nanoseconds`

If the unit is not specified, the value is interpreted as a *number of seconds*.

Examples
    * :literal:`"5s"`, :literal:`"5"` (5 seconds)
    * :literal:`"42 milliseconds"`
    * :literal:`"1.5 days"`

Complete Example
----------------

An example with all possible options set is given below:

.. literalinclude:: example_config.json
    :language: json
