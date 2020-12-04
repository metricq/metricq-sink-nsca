``metricq-sink-nsca``
=====================

|PyPI version|
|Documentation|

.. |PyPI version| image:: https://img.shields.io/pypi/v/metricq-sink-nsca.svg
   :target: PyPI_

.. |Documentation| image:: https://img.shields.io/badge/Documentation-here-green.svg
   :target: Documentation_

This tool is a MetricQ sink that sends passive service check results for
metrics, based on their availability and value range.

Installation
------------

Install the latest release of `metric-sink-nsca` from PyPI_:

.. code-block:: shell

    $ pip install metric-sink-nsca

To install the latest development version, clone
`the repo <https://github.com/metricq/metricq-sink-nsca>`_ and install from source:

.. code-block:: shell

    $ git clone https://github.com/metricq/metricq-sink-nsca.git /path/to/repo
    $ pip install /path/to/repo

Usage
-----

Basic setup (MetricQ management server, token etc) is configured via command
line; for more information, issue:

.. code-block:: shell

   $ metricq-sink-nsca --help

The check configuration is supplied by the MetricQ management-software on
startup, which is a JSON dict in the form of

.. code-block:: json

   {
      "reporting_host": "<address>",
      "nsca": { ... },
      "checks": { ... },
      "resend_interval": "<duration>"
   }

Here, ``"reporting_host"`` is the name of the host for which the check results
are reported as configured in Nagios/Centreon (defaults to the output of
``hostname(1)``).
``"nsca"`` contains the NSCA host configuration: ``nsca.host`` is the address
of the host running the NSCA daemon (see ``-H``-flag of ``send_nsca``),
``nsca.password`` and ``nsca.encryption_method`` are strings as used in
``send_nsca``-configuration format.
The duration specified by ``resend_interval`` is an optional default for all
checks, see below_ for its per-check configuration.

Per-check configuration
'''''''''''''''''''''''

The dictionary ``"checks"`` specifies service checks by their name:

.. code-block:: json

   "<check name>":
   {
      "metrics": [
         <name>, ...
      ],
      "warning_above": <value>,
      "warning_below": <value>,
      "critical_above": <value>,
      "critical_below": <value>,
      "ignore": [<value>, ...],
      "timeout": <duration>
   }

Of these keys, only ``"metrics"`` is mandatory, it specifies a *nonempty* list
of metric names that this check provides results for.  The remaining keys are
optional:

``{warning,critical}_{above,below}`` (number)
   Send a check result of state *WARNING* (resp. *CRITICAL*) to the NSCA host
   if values of the monitored metrics exceed (resp. fall below) the numerical
   threshold set by ``<value>``.  Note that the warning range must be properly
   contained within the critical range, i.e.::

      critical_below < warning_below < warning_above < critical_above

``ignore`` (list of numbers)
    Ignore these values when checking for abnormal values, even if they fall
    within the warning resp. critical range.  This is useful for faulty sources
    which spuriously report erroneous values.

``timeout`` (duration string)
   Send a check result of state *CRITICAL* to the NSCA host if consecutive
   values arrive apart more than the specified duration.  The duration is
   of the form of  ``<value><unit>``, e.g. ``30s`` or ``5min``.

.. _below:

``resend_interval`` (duration string)
    Minimum time interval at which this check should trigger reports, even if
    its overall state did not change.  This is useful for keeping the
    Centreon/Nagios host up-to-date and signaling that this passive check is
    not dead.

    Format is the same as for ``timeout``.


Examples
--------

For Nagios-host ``hvac-monitoring`` and service *Temperature*, check that
temperature readings in Room *A* and *B* do not exceed certain thresholds, and
that they arrive *at least* every 5 minutes.  Also, a temperature reading of
0.0℃ should be ignored.

.. code-block:: json

   {
      "reporting_host": "hvac-monitoring",
      "nsca": {
        "host": "192.0.2.1",
        "password": "hunter2",
        "encryption_method": "blowfish"
      },
      "checks": {
         "Temperature": {
            "metrics": [
               "room_a.temperature",
               "room_b.temperature"
            ],
            "warning_above": 40.0,
            "critical_above": 50.0,
            "ignore": [0.0],
            "timeout": "5min"
         }
      }
   }

License
-------

::

  metricq-sink-nsca
  Copyright (C) 2019  Technische Universität Dresden

  This program is free software: you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation, either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <https://www.gnu.org/licenses/>.

.. _PyPI: https://pypi.python.org/pypi/metricq-sink-nsca/
.. _Documentation: https://metricq.github.io/metricq-sink-nsca
