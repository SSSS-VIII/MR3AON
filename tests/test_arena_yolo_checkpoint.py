"""CPU serialization regressions; no GPU, original client or training required."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

try:
    import torch
except ImportError:
    torch = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_yolo_checkpoint import Fp32BestExporter, audit_fp32_state, install_fp32_export


@unittest.skipIf(torch is None, 'CPU PyTorch is required for checkpoint serialization tests')
class Fp32CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name) / 'fit'
        self.profile = Path(self.temp.name) / 'profile.json'
        self.profile.write_text(json.dumps({'classes': [{'name': 'player'}]}))
        # Existing torch modules exercise real running buffers and serialization.
        self.model = torch.nn.Sequential(torch.nn.BatchNorm2d(1)).float()
        self.model.names = {0: 'player'}
        self.model[0].running_var.fill_(2_740_721.)
        self.trainer = SimpleNamespace(epoch=0, ema=SimpleNamespace(ema=self.model, updates=5),
                                       fitness=.7, metrics={'mAP': .7}, args=SimpleNamespace(task='obb'))
        self.exporter = Fp32BestExporter(self.output, self.profile)

    def export(self):
        self.exporter.before_validation(self.trainer)
        self.exporter.after_standard_save(self.trainer)

    def test_preserves_large_bn_variance_and_live_model_state(self):
        self.model.train()
        self.export()
        saved = torch.load(self.exporter.best_path, map_location='cpu', weights_only=False)
        self.assertEqual(saved['model'][0].running_var.dtype, torch.float32)
        self.assertTrue(torch.equal(saved['model'][0].running_var, self.model[0].running_var))
        self.assertGreater(float(saved['model'][0].running_var[0]), 65504)
        self.assertTrue(self.model.training)
        self.assertTrue(self.model[0].training)
        audit = json.loads((self.output / 'fp32-best.json').read_text())
        self.assertEqual(audit['before_validation']['fp16_overflow_values'], 1)
        self.assertTrue(audit['validation_preserved_floating_state'])
        self.assertEqual(audit['checkpoint_sha256'], hashlib.sha256(self.exporter.best_path.read_bytes()).hexdigest())
        self.assertEqual((self.output / 'profile.json').read_bytes(), self.profile.read_bytes())

    def test_rejects_nonfinite_and_already_reduced_precision(self):
        for value in (float('nan'), float('inf')):
            self.model[0].running_var.fill_(value)
            with self.assertRaisesRegex(ValueError, 'non-finite or non-FP32'):
                self.exporter.before_validation(self.trainer)
        self.model[0].running_var.fill_(1.)
        self.model.half()
        with self.assertRaisesRegex(ValueError, 'non-finite or non-FP32'):
            audit_fp32_state(self.model)
        self.assertFalse(self.exporter.best_path.exists())

    def test_lower_fitness_or_bad_post_state_cannot_replace_good_checkpoint(self):
        self.export()
        good = self.exporter.best_path.read_bytes()
        self.trainer.epoch = 1
        self.trainer.fitness = .6
        self.model[0].running_var.fill_(500_000.)
        self.export()
        self.assertEqual(self.exporter.best_path.read_bytes(), good)
        self.assertFalse(json.loads((self.output / 'fp32-epoch-0002.json').read_text())['exported'])
        self.trainer.epoch = 2
        self.trainer.fitness = .8
        self.exporter.before_validation(self.trainer)
        self.model[0].running_var.fill_(float('nan'))
        with self.assertRaisesRegex(ValueError, 'non-finite'):
            self.exporter.after_standard_save(self.trainer)
        self.assertEqual(self.exporter.best_path.read_bytes(), good)

    def test_exports_prevalidation_snapshot_and_records_validation_mutation(self):
        self.exporter.before_validation(self.trainer)
        self.model[0].running_var.fill_(65504.)
        self.exporter.after_standard_save(self.trainer)
        saved = torch.load(self.exporter.best_path, map_location='cpu', weights_only=False)
        self.assertEqual(float(saved['model'][0].running_var[0]), 2_740_721.)
        audit = json.loads((self.output / 'fp32-best.json').read_text())
        self.assertFalse(audit['validation_preserved_floating_state'])

    def test_uses_only_official_callbacks_and_rejects_stale_snapshot(self):
        callbacks = {}
        model = SimpleNamespace(add_callback=lambda name, callback: callbacks.update({name: callback}))
        exporter = install_fp32_export(model, self.output, self.profile)
        self.assertEqual(set(callbacks), {'on_train_epoch_end', 'on_model_save'})
        callbacks['on_train_epoch_end'](self.trainer)
        self.trainer.epoch = 1
        with self.assertRaisesRegex(ValueError, 'matching pre-validation'):
            callbacks['on_model_save'](self.trainer)
        self.assertFalse(exporter.best_path.exists())


if __name__ == '__main__':
    unittest.main()
