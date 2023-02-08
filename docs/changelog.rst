Changelog
=========

* :release:`1.8.3 <2023-02-08>`
* :feature: Adds Dockerfile and automated build for docker images available on Docker Hub
* :support:`-` Update :code:`metricq` dependency to 4.0.0
* :support:`-` Update :code:`python` dependency to 3.10


* :release:`1.8.2 <2022-02-14>`
* :bug:`49` Fixes a bug where reconfiguring a check configuration at runtime did not update the overrides for existing checks.

* :release:`1.8.1 <2021-07-23>` 39
* :support:`39` Improved log messages to aid debugging in production
  (see `#38 <https://github.com/metricq/metricq-sink-nsca/issues/38>`_).

* :release:`1.8.0 <2021-06-29>`
* :feature:`34` Add a way to globally ignore a set of metrics via the :literal:`"overrides"` section in the configuration.
  See :ref:`the documentation<overrides>` for more information.

* :release:`1.7.1 <2021-06-15>`
* :bug:`35` Fix a bug where reconfiguration of a check configuration at runtime would result in an error or misconfiguration.

* :release:`1.7.0 <2021-06-08>`
* :bug:`29 major` Fix a bug where checks would report a timeout error even after they were removed via dynamic reconfiguration.
* :support:`33` Miscellaneous fixes and improvements
* :feature:`27` (via :issue:`26`) Optionally use :code:`uvloop`-based event loop.
  To enable, install :code:`uvloop` directly, or the :code:`[uvloop]` extra
  (:code:`pip install 'metricq-sink-nsca[uvloop]'`).
* :support:`-` Update :code:`metricq` dependency to 3.0.0

* :release:`1.6.2 <2021-05-06>`
* :bug:`23` Ignore non-monotonous data points

* :release:`1.6.1 <2021-03-23>`
* :bug:`19` Update :code:`metricq` dependency to 2.0.0

* :release:`1.6.0 <2020-12-04>`
* :support:`10` :code:`metricq-sink-nsca` is now `available on PyPI <https://pypi.org/project/metricq-sink-nsca>`_!
* :bug:`9 major` Gracefully handle non-monotonic metrics
* :feature:`6` Add Sphinx-based documentation, read it `here <https://metricq.github.io/metricq-sink-nsca/>`_!
* :feature:`3` Implement soft-fail post-processing for state changes
* :feature:`1` Make parsing of DataChunks optional
* :feature:`-` Add a dry-run mode (:code:`-n/--dry-run`) that does not call :code:`send_nsca`

* :release:`1.5.0 <2020-05-12>`
* :support:`-` Use :code:`send_nsca` CLI tool instead of python reimplementation (:code:`aionsca`)

* :release:`1.4.0 <2020-02-05>`
* :bug:`- major` Ignore :literal:`NaN` values from incoming datachunks

* :release:`1.3.0 <2020-01-30>`
* :feature:`-` Only restart checks whose configuration changed
* :support:`-` Use stable :code:`metricq` version
* :feature:`-` Add custom verbosity CLI option (:code:`-v foo=INFO,foo.bar=VERBOSE`)
* :feature:`-` Make interval for re-sending check states configurable
* :bug:`- major` Various bugfixes

* :release:`1.2.0 <2019-09-11>`
* :feature:`-` Add a basic plugin system

* :release:`1.1.0 <2019-09-03>`
* :bug:`- major` Throttle amount of reports sent to NSCA host

* :release:`1.1.0 <2019-09-03>`
* :feature:`-` Initial release
