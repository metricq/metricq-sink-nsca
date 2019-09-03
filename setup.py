# metricq-sink-nsca
# Copyright (C) 2019 ZIH, Technische Universitaet Dresden, Federal Republic of Germany
#
# All rights reserved.
#
# This file is part of metricq.
#
# metricq is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# metricq is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with metricq.  If not, see <http://www.gnu.org/licenses/>.
from setuptools import setup

setup(
    name="metricq_sink_nsca",
    version="1.0",
    author="TU Dresden",
    python_requires=">=3.7",
    packages=["metricq_sink_nsca"],
    scripts=[],
    entry_points="""
      [console_scripts]
      metricq-sink-nsca=metricq_sink_nsca:main
      """,
    install_requires=["click", "click-log", "metricq>=0.0", "aionsca==1.0.0.dev2"],
)
