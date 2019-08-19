``metricq-sink-nsca``
=====================

This tool is a MetricQ sink that sends passive service check results for
metrics, based on their availability and value range.

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
      "reporting_host": <address>,
      "nsca_host": <address>,
      "checks": { ... }
   }

Here, ``"reporting_host"`` is the name of the host for which the check results
are reported as configured in Nagios/Centreon (defaults to the output of
``hostname(1)``);  ``"nsca_host"`` is the address of the host running the NSCA
daemon (see ``-H``-flag of ``send_nsca``).  The dictionary ``"checks"``
specifies service checks by their name:

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

``timeout`` (string)
   Send a check result of state *CRITICAL* to the NSCA host if consecutive
   values arrive apart more than the specified duration.  The duration is
   of the form of  ``<value><unit>``, e.g. ``30s`` or ``5min``.


Examples
--------

For Nagios-host ``hvac-monitoring`` and service *Temperature*, check that
temperature readings in Room *A* and *B* do not exceed certain thresholds, and
that they do not arrive more than 5 minutes apart:

.. code-block:: json

   {
      "reporting_host": "hvac-monitoring",
      "nsca_host": "192.0.2.1",
      "checks": {
         "Temperature": {
            "metrics": [
               "room_a.temperature",
               "room_b.temperature"
            ],
            "warning_above": 40.0,
            "critical_above": 50.0,
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
