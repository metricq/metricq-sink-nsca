Changelog
=========

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
