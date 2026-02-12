from __future__ import annotations

import os
import textwrap
import unittest

import mock

from jobrunner import db, info, plugins, utils
from jobrunner.service.registry import registerServices

from .helpers import capturedOutput, resetEnv


def setUpModule():
    resetEnv()
    registerServices(testing=True)
    os.environ["HOSTNAME"] = "testHostname"
    os.environ["USER"] = "somebody"


def _makeJob(uidx, cmd, key=None, depends=None):
    """Create a minimal JobInfo suitable for tree display tests."""
    mockPlug = mock.MagicMock(plugins.Plugins)
    mockPlug.workspaceIdentity.return_value = "WS"
    mockPlug.workspaceProject.return_value = ("proj", True)
    utils.MOD_STATE.plugins = mockPlug
    parent = mock.MagicMock(db.JobsBase)
    parent.inactive = mock.MagicMock(db.DatabaseBase)
    parent.active = mock.MagicMock(db.DatabaseBase)
    job = info.JobInfo(uidx, key=key)
    job.isolate = False
    job.setCmd(cmd)
    job.parent = parent
    job.start(job.parent)
    if depends is not None:
        # Set depends directly as list of keys (bypass the setter
        # which expects JobInfo objects).
        # pylint: disable=protected-access
        job._depends = depends
    return job


class TestBuildChildrenMap(unittest.TestCase):
    """Tests for JobsBase._buildChildrenMap static method."""

    def test_emptyCache(self):
        result = db.JobsBase._buildChildrenMap({})
        self.assertEqual(result, {})

    def test_noDeps(self):
        """Jobs with no dependencies produce no children."""
        j1 = _makeJob(1, ["cmd1"], key="j1")
        j2 = _makeJob(2, ["cmd2"], key="j2")
        cache = {"j1": j1, "j2": j2}
        result = db.JobsBase._buildChildrenMap(cache)
        self.assertEqual(result, {})

    def test_linearChain(self):
        """A -> B -> C yields A->[B], B->[C]."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["B"])
        cache = {"A": jA, "B": jB, "C": jC}
        result = db.JobsBase._buildChildrenMap(cache)
        self.assertEqual(result["A"], ["B"])
        self.assertEqual(result["B"], ["C"])
        self.assertNotIn("C", result)

    def test_diamondDag(self):
        """Diamond: A has children B and C, both have child D."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["A"])
        jD = _makeJob(4, ["cmdD"], key="D", depends=["B", "C"])
        cache = {"A": jA, "B": jB, "C": jC, "D": jD}
        result = db.JobsBase._buildChildrenMap(cache)
        self.assertEqual(sorted(result["A"]), ["B", "C"])
        self.assertEqual(result["B"], ["D"])
        self.assertEqual(result["C"], ["D"])
        self.assertNotIn("D", result)

    def test_missingParentIgnored(self):
        """Dependencies on keys not in the cache are ignored."""
        jB = _makeJob(2, ["cmdB"], key="B", depends=["ghost"])
        cache = {"B": jB}
        result = db.JobsBase._buildChildrenMap(cache)
        self.assertEqual(result, {})

    def test_multipleChildren(self):
        """A single parent with multiple children."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["A"])
        jD = _makeJob(4, ["cmdD"], key="D", depends=["A"])
        cache = {"A": jA, "B": jB, "C": jC, "D": jD}
        result = db.JobsBase._buildChildrenMap(cache)
        self.assertEqual(sorted(result["A"]), ["B", "C", "D"])


class TestRenderTreeNode(unittest.TestCase):
    """Tests for JobsBase._renderTreeNode."""

    def setUp(self):
        self.jobs = mock.MagicMock(db.JobsBase)
        self.jobs._renderTreeNode = db.JobsBase._renderTreeNode.__get__(self.jobs)

    def _render(self, key, jobCache, childrenMap):
        """Render tree and return captured output lines."""
        with capturedOutput() as (out, _):
            self.jobs._renderTreeNode(
                key,
                jobCache,
                childrenMap,
                "",
                True,
                True,
            )
        return out.getvalue().splitlines()

    def assertOutput(self, expected, lines):
        self.assertEqual(
            textwrap.dedent(expected).strip(),
            "\n".join(lines),
        )

    def test_singleRoot(self):
        """A root job with no children prints just the job."""
        jA = _makeJob(1, ["cmdA"], key="A")
        lines = self._render("A", {"A": jA}, {})
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
      """,
            lines,
        )

    def test_rootWithOneChild(self):
        """Root with one child shows root then └── child."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        children = {"A": ["B"]}
        cache = {"A": jA, "B": jB}
        lines = self._render("A", cache, children)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
      """,
            lines,
        )

    def test_rootWithTwoChildren(self):
        """Root with two children: first uses ├──, last uses └──."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        jC = _makeJob(3, ["cmdC"], key="C")
        children = {"A": ["B", "C"]}
        cache = {"A": jA, "B": jB, "C": jC}
        lines = self._render("A", cache, children)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         ├── 0:00:00 [B] cmdB
         └── 0:00:00 [C] cmdC
      """,
            lines,
        )

    def test_deepNesting(self):
        """A -> B -> C produces nested tree with continuation line."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        jC = _makeJob(3, ["cmdC"], key="C")
        children = {"A": ["B"], "B": ["C"]}
        cache = {"A": jA, "B": jB, "C": jC}
        lines = self._render("A", cache, children)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
             └── 0:00:00 [C] cmdC
      """,
            lines,
        )

    def test_continuationLineForNonLastChild(self):
        """Non-last children produce │ continuation in prefix."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        jC = _makeJob(3, ["cmdC"], key="C")
        jD = _makeJob(4, ["cmdD"], key="D")
        # A has children B and C; B has child D
        children = {"A": ["B", "C"], "B": ["D"]}
        cache = {"A": jA, "B": jB, "C": jC, "D": jD}
        lines = self._render("A", cache, children)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         ├── 0:00:00 [B] cmdB
         │   └── 0:00:00 [D] cmdD
         └── 0:00:00 [C] cmdC
      """,
            lines,
        )

    def test_missingKeyProducesNoOutput(self):
        """Rendering a key not in the cache produces nothing."""
        lines = self._render("missing", {}, {})
        self.assertOutput("", lines)

    def test_cyclePrevention(self):
        """Ancestor tracking prevents infinite recursion in cycles."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        # A -> B -> A (cycle via childrenMap)
        children = {"A": ["B"], "B": ["A"]}
        cache = {"A": jA, "B": jB}
        # Should not recurse infinitely; A is printed again but
        # its children are not expanded (A is in ancestors)
        lines = self._render("A", cache, children)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
             └── 0:00:00 [A] cmdA
      """,
            lines,
        )


class TestListDbTreeDisplay(unittest.TestCase):
    """Integration tests for the tree display path in listDb."""

    def _makeJobsBase(self, activeJobs):
        """Create a minimal JobsBase-like object for listDb testing.

        activeJobs is a list of JobInfo objects to place in the
        active database.
        """
        config = mock.MagicMock()
        config.verbose = None
        plugs = mock.MagicMock(plugins.Plugins)
        plugs.workspaceIdentity.return_value = "WS"
        plugs.workspaceProject.return_value = ("proj", True)

        jobs = mock.MagicMock(spec=db.JobsBase)
        jobs.config = config
        # Bind real methods
        jobs._buildChildrenMap = db.JobsBase._buildChildrenMap
        jobs._renderTreeNode = db.JobsBase._renderTreeNode.__get__(jobs)
        jobs.filterJobs = db.JobsBase.filterJobs.__get__(jobs)
        jobs.listDb = db.JobsBase.listDb.__get__(jobs)
        jobs.getDbSorted = db.JobsBase.getDbSorted.__get__(jobs)

        # Set up active db mock (no spec so values() is available)
        activeDb = mock.MagicMock()
        dbDict = {}
        for j in activeJobs:
            dbDict[j.key] = j
        activeDb.__contains__ = lambda self_, k: k in dbDict
        activeDb.__getitem__ = lambda self_, k: dbDict[k]
        activeDb.keys.return_value = list(dbDict.keys())
        activeDb.filterJobs.side_effect = lambda k: k not in db.DatabaseMeta.special
        jobList = list(dbDict.values())
        activeDb.values.side_effect = lambda cache=None: jobList

        jobs.active = activeDb
        return jobs

    def _listDb(self, jobsBase):
        """Run listDb and return captured output lines."""
        with capturedOutput() as (out, _):
            jobsBase.listDb(
                jobsBase.active,
                None,
                includeReminders=False,
            )
        return out.getvalue().splitlines()

    def assertOutput(self, expected, lines):
        self.assertEqual(
            textwrap.dedent(expected).strip(),
            "\n".join(lines),
        )

    def test_noJobs(self):
        """Empty active db prints (None)."""
        jobs = self._makeJobsBase([])
        lines = self._listDb(jobs)
        self.assertOutput("(None)", lines)

    def test_singleJobNoDeps(self):
        """A single job with no deps prints as a plain line."""
        jA = _makeJob(1, ["echo", "hello"], key="A")
        jobs = self._makeJobsBase([jA])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] echo hello
      """,
            lines,
        )

    def test_twoIndependentJobs(self):
        """Two jobs with no deps each print as plain lines."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B")
        jobs = self._makeJobsBase([jA, jB])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         0:00:00 [B] cmdB
      """,
            lines,
        )

    def test_parentChildTree(self):
        """Parent with child shows tree with box-drawing characters."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jobs = self._makeJobsBase([jA, jB])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
      """,
            lines,
        )

    def test_childNotDuplicatedAsRoot(self):
        """A child job should not appear again as a standalone root."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jobs = self._makeJobsBase([jA, jB])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
      """,
            lines,
        )

    def test_chainOfThree(self):
        """A -> B -> C shows as a nested tree."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["B"])
        jobs = self._makeJobsBase([jA, jB, jC])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         └── 0:00:00 [B] cmdB
             └── 0:00:00 [C] cmdC
      """,
            lines,
        )

    def test_diamondDag(self):
        """Diamond: A -> B, A -> C, B -> D, C -> D."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["A"])
        jD = _makeJob(4, ["cmdD"], key="D", depends=["B", "C"])
        jobs = self._makeJobsBase([jA, jB, jC, jD])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         ├── 0:00:00 [B] cmdB
         │   └── 0:00:00 [D] cmdD
         └── 0:00:00 [C] cmdC
             └── 0:00:00 [D] cmdD
      """,
            lines,
        )

    def test_diamondDagWithTail(self):
        """Diamond + tail: A -> B, A -> C, B -> D, C -> D, D -> E."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jC = _makeJob(3, ["cmdC"], key="C", depends=["A"])
        jD = _makeJob(4, ["cmdD"], key="D", depends=["B", "C"])
        jE = _makeJob(5, ["cmdE"], key="E", depends=["D"])
        jobs = self._makeJobsBase([jA, jB, jC, jD, jE])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
         ├── 0:00:00 [B] cmdB
         │   └── 0:00:00 [D] cmdD
         │       └── 0:00:00 [E] cmdE
         └── 0:00:00 [C] cmdC
             └── 0:00:00 [D] cmdD
                 └── 0:00:00 [E] cmdE
      """,
            lines,
        )

    def test_reminderFiltered(self):
        """Reminder jobs are excluded when includeReminders=False."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jR = _makeJob(2, ["(reminder)"], key="R")
        jR.reminder = "do something"
        jobs = self._makeJobsBase([jA, jR])
        lines = self._listDb(jobs)
        self.assertOutput(
            """\
         0:00:00 [A] cmdA
      """,
            lines,
        )

    def test_verboseFallsBackToFlatList(self):
        """When config.verbose is set, tree display is not used."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jobs = self._makeJobsBase([jA, jB])
        jobs.config.verbose = ["v"]
        with capturedOutput() as (out, _):
            jobs.listDb(
                jobs.active,
                None,
                includeReminders=False,
            )
        output = out.getvalue()
        # Verbose uses job.detail(), which includes SPACER lines
        self.assertNotIn("└──", output)
        self.assertNotIn("├──", output)

    def test_inactiveDbUseFlatList(self):
        """Inactive database always uses flat list, not tree."""
        jA = _makeJob(1, ["cmdA"], key="A")
        jB = _makeJob(2, ["cmdB"], key="B", depends=["A"])
        jobs = self._makeJobsBase([jA, jB])

        # Create an inactive db (no spec so values() is available)
        inactiveDb = mock.MagicMock()
        dbDict = {"A": jA, "B": jB}
        inactiveDb.__contains__ = lambda self_, k: k in dbDict
        inactiveDb.__getitem__ = lambda self_, k: dbDict[k]
        inactiveDb.keys.return_value = list(dbDict.keys())
        inactiveDb.filterJobs.side_effect = lambda k: (
            k not in db.DatabaseMeta.special
        )
        jobList = list(dbDict.values())
        inactiveDb.values.side_effect = lambda cache=None: jobList
        jobs.inactive = inactiveDb

        with capturedOutput() as (out, _):
            jobs.listDb(
                inactiveDb,
                None,
                includeReminders=False,
            )
        output = out.getvalue()
        # No tree chars for inactive db
        self.assertNotIn("└──", output)
        self.assertNotIn("├──", output)
