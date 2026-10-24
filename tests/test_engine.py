import unittest
from app.engine import RadioWorker
from app.scenario import preset


class EngineTests(unittest.TestCase):
    def test_native_worker_failure_is_contained_and_scene_can_restart(self):
        worker=RadioWorker(preset('empty'))
        worker.process.terminate();worker.process.join(timeout=5)
        with self.assertRaisesRegex(RuntimeError,'worker'):
            worker.sample([2,2,1])
        worker.close()
        replacement=RadioWorker(preset('empty'))
        try:self.assertGreater(replacement.sample([2,2,1])['path_count'],0)
        finally:replacement.close()


if __name__=='__main__':unittest.main()
