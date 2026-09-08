"""Replay checked-in synthetic fixtures; labels do not represent live models."""
from regatlas.suite import load_suite
from regatlas.replay import RecordingClient, replay_suite
from regatlas.align import align_spans
from regatlas.delta import aggregate, render_markdown
suite=load_suite('suites/toolcalling.yaml')
baseline=replay_suite(suite,RecordingClient.from_file('tests/fixtures/opus-4.responses.json',model_version='baseline-fixture'))
candidate=replay_suite(suite,RecordingClient.from_file('tests/fixtures/opus-5.responses.json',model_version='candidate-fixture'))
differences=align_spans(baseline,candidate)
print(render_markdown(aggregate(differences),from_model='baseline-fixture',to_model='candidate-fixture',suite_name=suite.name,total_tasks=len(differences)))
