"""Lossless, finite FP32 EMA export through official Ultralytics callbacks.

Standard Trainer checkpoints remain untouched. Exporting a checkpoint does not
accept its detection quality or select it as the runtime model.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
from importlib.metadata import PackageNotFoundError, version
import json
import math
from pathlib import Path


def audit_fp32_state(model):
    """Reject already reduced precision/nonfinite state; never clamp tensors."""
    import torch
    tensors = {}; digest = hashlib.sha256(); errors = []
    for name, value in model.state_dict().items():
        if not value.is_floating_point():
            continue
        value = value.detach().cpu().contiguous()
        finite = bool(torch.isfinite(value).all())
        if value.dtype != torch.float32 or not finite:
            errors.append(f'{name}: dtype={value.dtype}, finite={finite}')
        raw = value.numpy().tobytes() if value.dtype != torch.bfloat16 else value.float().numpy().tobytes()
        tensor_sha = hashlib.sha256(raw).hexdigest()
        digest.update(name.encode()); digest.update(str(value.dtype).encode())
        digest.update(str(tuple(value.shape)).encode()); digest.update(raw)
        tensors[name] = dict(dtype=str(value.dtype), numel=value.numel(), sha256=tensor_sha,
                             finite=finite, abs_max=float(value.abs().max()) if value.numel() else 0.,
                             exceeds_fp16=int((value.abs() > 65504).sum()))
    result = dict(floating_state_sha256=digest.hexdigest(), tensors=tensors,
                  fp16_overflow_values=sum(v['exceeds_fp16'] for v in tensors.values()))
    if errors:
        raise ValueError('Refusing non-finite or non-FP32 EMA export: ' + '; '.join(errors))
    return result


def _json_write(path, payload):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(payload, indent=2, allow_nan=False) + '\n')
    temporary.replace(path)


class Fp32BestExporter:
    """Preserve the pre-validation EMA selected by the standard Trainer metric.

    The snapshot precedes validation so later validation/save precision changes
    cannot corrupt it. Post-validation state is audited independently. The
    artifact uses the stock YOLO checkpoint schema and original architecture.
    """
    def __init__(self, output, profile=None):
        self.output = Path(output)
        self.best_path = self.output / 'weights/best-fp32.pt'
        self.profile_path = Path(profile) if profile is not None else None
        self.profile_bytes = self.profile_path.read_bytes() if self.profile_path and self.profile_path.is_file() else None
        self.snapshot = None
        self.snapshot_epoch = None
        self.before_audit = None
        self.best_fitness = -math.inf

    def before_validation(self, trainer):
        """Official on_train_epoch_end hook; does not mutate the live EMA."""
        self.snapshot = None
        self.snapshot_epoch = None
        self.before_audit = None
        snapshot = deepcopy(trainer.ema.ema).cpu().eval()
        if hasattr(snapshot, 'criterion'):
            snapshot.criterion = None
        audit = audit_fp32_state(snapshot)
        if self.profile_bytes is not None:
            profile = json.loads(self.profile_bytes)
            if list(snapshot.names.values()) != [c['name'] for c in profile['classes']]:
                raise ValueError('FP32 EMA and native resource profile differ')
        self.snapshot, self.snapshot_epoch, self.before_audit = snapshot, trainer.epoch, audit

    def after_standard_save(self, trainer):
        """Official on_model_save hook, separate from standard FP16 files."""
        import torch
        if self.snapshot is None or self.snapshot_epoch != trainer.epoch:
            raise ValueError('No matching pre-validation FP32 EMA snapshot')
        after = audit_fp32_state(trainer.ema.ema)
        fitness = float(trainer.fitness)
        if not math.isfinite(fitness):
            raise ValueError('Refusing FP32 export with non-finite validation fitness')
        metrics = {k: float(v) for k, v in trainer.metrics.items()}
        if any(not math.isfinite(v) for v in metrics.values()):
            raise ValueError('Refusing FP32 export with non-finite validation metrics')
        audit = dict(epoch_one_based=trainer.epoch + 1, fitness=fitness,
                     validation_metrics=metrics, before_validation=self.before_audit,
                     after_validation=after,
                     validation_preserved_floating_state=(self.before_audit['floating_state_sha256'] == after['floating_state_sha256']),
                     selected_by='standard Trainer validation fitness; detection/native acceptance is separate',
                     exported=False)
        self.output.mkdir(parents=True, exist_ok=True)
        audit_path = self.output / f'fp32-epoch-{trainer.epoch + 1:04d}.json'
        if fitness < self.best_fitness:
            _json_write(audit_path, audit)
            self.snapshot = None
            return
        try:
            sdk_version = version('ultralytics')
        except PackageNotFoundError:
            sdk_version = None
        payload = dict(epoch=trainer.epoch, model=self.snapshot, ema=None,
                       optimizer=None, updates=getattr(trainer.ema, 'updates', None),
                       train_args=dict(vars(trainer.args)), train_metrics={**metrics, 'fitness': fitness},
                       date=datetime.now(timezone.utc).isoformat(), version=sdk_version,
                       export_scope='unmodified pre-validation FP32 EMA; original YOLO architecture')
        self.best_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.best_path.with_suffix('.pt.tmp')
        torch.save(payload, temporary)
        temporary.replace(self.best_path)
        self.best_fitness = fitness
        if self.profile_bytes is not None:
            (self.output / 'profile.json').write_bytes(self.profile_bytes)
        audit.update(exported=True, checkpoint=str(self.best_path),
                     checkpoint_sha256=hashlib.sha256(self.best_path.read_bytes()).hexdigest(),
                     profile_sha256=hashlib.sha256(self.profile_bytes).hexdigest() if self.profile_bytes is not None else None)
        _json_write(audit_path, audit)
        _json_write(self.output / 'fp32-best.json', audit)
        self.snapshot = None


def install_fp32_export(model, output, profile=None):
    """Attach supported callbacks without replacing Trainer or its save path."""
    exporter = Fp32BestExporter(output, profile)
    model.add_callback('on_train_epoch_end', exporter.before_validation)
    model.add_callback('on_model_save', exporter.after_standard_save)
    return exporter
