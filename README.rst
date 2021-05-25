``metricq-sink-nsca``
=====================

|PyPI version|
|documentation|

.. |PyPI version| image:: https://img.shields.io/pypi/v/metricq-sink-nsca.svg
   :target: PyPI_

.. |Documentation| image:: https://img.shields.io/badge/Documentation-here-green.svg
   :target: documentation_

This tool is a MetricQ sink that sends passive service check results for
metrics, based on their availability and value range.

Installation
------------

Install the latest release of `metric-sink-nsca` from PyPI_:

.. code-block:: console

    $ pip install metric-sink-nsca

Optionally, install the :code:`[uvloop]` extra to use an optimized event loop implementation `based on uvloop <https://pypi.org/project/uvloop/>`_:

.. code-block:: console

    $ pip install 'metric-sink-nsca[uvloop]'

Developement version
~~~~~~~~~~~~~~~~~~~~

To install the latest development version, clone
`the repo <https://github.com/metricq/metricq-sink-nsca>`_ and install from source:

.. code-block:: console

    $ git clone https://github.com/metricq/metricq-sink-nsca.git /path/to/repo
    $ pip install /path/to/repo

Usage and Configuration
-----------------------

Basic setup (MetricQ management server, client token etc) is configured via
command line; for more information, issue:

.. code-block:: console

   $ metricq-sink-nsca --help

All other configuration is provided over the MetricQ network.
See section `Configuration <https://metricq.github.io/metricq-sink-nsca/usage/configuration.html>`_
of the documentation_ for more information.


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
.. _documentation: https://metricq.github.io/metricq-sink-nsca
