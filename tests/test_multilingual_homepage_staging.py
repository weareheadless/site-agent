import copy

import pytest

from site_agent.core.design_contracts import PageBuildRequest
from site_agent.hands import opencode_runner as runner
from tests.test_design_builder import _composed_plan, _payload_first_request


def request():
    value = _payload_first_request().to_dict()
    value['content']['site_intake']['site'].update(locales=['es', 'en'], default_locale='es')
    return PageBuildRequest.from_dict(value)


def plan():
    value = _composed_plan({'headline': 'Tu estilo.', 'body': 'Color personal.', 'primary_action': 'Conversemos'})
    value.copy_deck.update(locale='es', translations={
        'en': {'meta_description': 'Personal colour.', 'section_labels': {'home-opening': 'Introduction'},
               'entry_text': {'home.hero.heading': 'Your style.', 'home.hero.introduction': 'Personal colour.',
                              'home.hero.primary-action': 'Let us talk'}},
    })
    return value


class Payload:
    def __init__(self):
        self.documents = {}
        self.writes = []

    def require_authoring_contract(self):
        return {'locales': ['es', 'en'], 'defaultLocale': 'es', 'enabled': {'collections': ['pages']},
                'schemaIdentity': 'schema-identity', 'authoringContractHash': 'authoring-hash'}

    def create(self, collection, data, *, locale):
        if self.documents:
            from site_agent.hands.payload_gateway import PayloadGatewayError
            raise PayloadGatewayError('route already exists', status_code=409)
        self.writes.append(locale)
        self.documents[locale] = {'id': 41, 'sourceId': 'pages:home', **copy.deepcopy(data),
                                  '_helloadaRevision': 'sha256:' + ('1' if locale == 'es' else '2') * 64}
        self.documents[locale]['sections'][0]['id'] = 'section-row'
        for index, entry in enumerate(self.documents[locale]['sections'][0]['entries']):
            entry['id'] = f'entry-row-{index}'
        return copy.deepcopy(self.documents[locale])

    def read(self, collection, *, identifier, identifier_kind, draft, locale):
        return copy.deepcopy(self.documents.get(locale) or self.documents['es'])

    def update(self, collection, identifier, data, *, locale, expected_hash, expected_fields):
        assert identifier == '41'
        assert data['sections'][0]['id'] == 'section-row'
        assert all(entry.get('id') == f'entry-row-{index}' for index, entry in enumerate(data['sections'][0]['entries']))
        assert expected_hash == (self.documents.get(locale) or self.documents['es'])['_helloadaRevision']
        self.writes.append(locale)
        self.documents[locale] = {'id': 41, 'sourceId': 'pages:home', **copy.deepcopy(data),
                                  '_helloadaRevision': 'sha256:' + '2' * 64}
        return copy.deepcopy(self.documents[locale])


def test_stages_complete_locale_content_with_stable_binding_keys():
    payload = Payload()
    staged = runner._stage_initial_homepage_payload({'payload_gateway': payload}, request(), plan())
    assert payload.writes == ['es', 'en']
    assert [item['locale'] for item in staged.content['payload_draft_receipts']] == ['es', 'en']
    original = payload.documents['es']['sections'][0]['entries']
    translated = payload.documents['en']['sections'][0]['entries']
    assert [item['key'] for item in original] == [item['key'] for item in translated]
    assert translated[0]['text'] == 'Your style.'
    assert original[0]['text'] == 'Tu estilo.'
    assert payload.documents['en']['seo']['description'] == 'Personal colour.'


@pytest.mark.parametrize('change', ['missing-language', 'missing-entry', 'extra-entry', 'wrong-default', 'runtime'])
def test_missing_or_mismatched_locale_coverage_stops_before_any_write(change):
    selected = plan()
    payload = Payload()
    if change == 'missing-language':
        selected.copy_deck['translations'] = {}
    elif change == 'missing-entry':
        del selected.copy_deck['translations']['en']['entry_text']['home.hero.heading']
    elif change == 'extra-entry':
        selected.copy_deck['translations']['en']['entry_text']['unknown'] = 'Unbound'
    elif change == 'wrong-default':
        selected.copy_deck['locale'] = 'en'
    else:
        payload.require_authoring_contract = lambda: {'locales': ['en'], 'defaultLocale': 'en', 'enabled': {'collections': ['pages']}}
    with pytest.raises(runner.RunnerError, match='locale|translation'):
        runner._stage_initial_homepage_payload({'payload_gateway': payload}, request(), selected)
    assert not payload.writes


def test_locale_recovery_reuses_every_saved_receipt_read_only(tmp_path):
    from site_agent.core.memory import Memory

    payload = Payload()
    selected = request()
    memory = Memory(tmp_path / 'stage.db')
    memory.create_design_run(run_id=selected.run_id, mode='production_candidate',
                             intake_json=selected.content['site_intake'], intake_hash='b' * 64,
                             base_sha=selected.base_sha, publishable=True,
                             candidate_ref=f'refs/ada-design/{selected.run_id}')
    try:
        first = runner._stage_initial_homepage_payload({'payload_gateway': payload, 'memory': memory}, selected, plan())
        second = runner._stage_initial_homepage_payload({'payload_gateway': payload, 'memory': memory}, selected, plan())
        assert first.content['payload_draft_receipts'] == second.content['payload_draft_receipts']
        assert payload.writes == ['es', 'en']
    finally:
        memory.close()


def test_translation_staging_checkpoint_resumes_without_rewriting_prior_locale(tmp_path):
    from site_agent.core.memory import Memory

    payload = Payload()
    selected = request()
    memory = Memory(tmp_path / 'stage.db')
    memory.create_design_run(run_id=selected.run_id, mode='production_candidate',
                             intake_json=selected.content['site_intake'], intake_hash='b' * 64,
                             base_sha=selected.base_sha, publishable=True,
                             candidate_ref=f'refs/ada-design/{selected.run_id}')
    update = payload.update
    def interrupted(*args, **kwargs):
        raise RuntimeError('interrupted before second locale save')
    payload.update = interrupted
    try:
        with pytest.raises(runner.RunnerError, match='interrupted'):
            runner._stage_initial_homepage_payload({'payload_gateway': payload, 'memory': memory}, selected, plan())
        assert [item['locale'] for item in memory.get_design_run(selected.run_id)['planning_json']['payload_draft_receipts']] == ['es']
        payload.update = update
        runner._stage_initial_homepage_payload({'payload_gateway': payload, 'memory': memory}, selected, plan())
        assert payload.writes == ['es', 'en']
    finally:
        memory.close()


class BrandedPayload(Payload):
    def __init__(self):
        super().__init__()
        self.globals = {locale: {'_helloadaRevision': 'sha256:' + '0' * 64} for locale in ('es', 'en')}

    def require_authoring_contract(self):
        value = super().require_authoring_contract()
        value['enabled']['globals'] = ['siteSettings']
        return value

    def read_global(self, slug, *, draft, locale):
        assert slug == 'siteSettings' and draft
        return copy.deepcopy(self.globals[locale])

    def update_global(self, slug, data, *, locale, expected_hash):
        assert expected_hash == self.globals[locale]['_helloadaRevision']
        self.globals[locale] = {**copy.deepcopy(data), '_helloadaRevision': 'sha256:' + ('3' if locale == 'es' else '4') * 64}
        return copy.deepcopy(self.globals[locale])


def branded_plan():
    selected = plan()
    selected.copy_deck['site_settings'] = {'siteName': 'North Star Studio', 'description': 'Color personal.',
                                           'tagline': '', 'footerTitle': '', 'footerNote': ''}
    selected.copy_deck['translations']['en']['site_settings'] = {'siteName': 'North Star Studio', 'description': 'Personal colour.',
                                                               'tagline': '', 'footerTitle': '', 'footerNote': ''}
    return selected


def test_exact_global_branding_is_bound_with_both_locale_page_receipts():
    payload = BrandedPayload()
    context = {'payload_gateway': payload}
    staged = runner._stage_initial_homepage_payload(context, request(), branded_plan())
    receipts = staged.content['payload_draft_receipts']
    assert [(item['kind'], item['locale']) for item in receipts] == [('collection', 'es'), ('collection', 'en'), ('global', 'es'), ('global', 'en')]
    assert context['_payload_candidate_receipts'] == receipts
    assert payload.globals['es']['siteName'] == payload.globals['en']['siteName'] == 'North Star Studio'
    assert payload.globals['en']['description'] == 'Personal colour.'


def test_missing_global_translation_is_rejected_before_any_page_mutation():
    payload = BrandedPayload()
    selected = branded_plan()
    del selected.copy_deck['translations']['en']['site_settings']
    with pytest.raises(runner.RunnerError, match='locale|settings'):
        runner._stage_initial_homepage_payload({'payload_gateway': payload}, request(), selected)
    assert payload.writes == []


def test_planned_global_identity_cannot_replace_the_confirmed_business_name():
    payload = BrandedPayload()
    selected = branded_plan()
    selected.copy_deck['site_settings']['siteName'] = 'Generic template brand'
    with pytest.raises(runner.RunnerError, match='confirmed business identity'):
        runner._stage_initial_homepage_payload({'payload_gateway': payload}, request(), selected)
    assert payload.writes == []


def test_initial_locale_runtime_preparation_leaves_adas_presentation_and_tenant_config_untouched(tmp_path):
    presentation = tmp_path / 'src/components/site/presentation/PagePresentation.tsx'
    presentation.parent.mkdir(parents=True)
    presentation.write_text('Ada owns the page composition')
    config = tmp_path / 'src/helloada.config.ts'
    config.write_text('Verified tenant config belongs to the release, not Ada')
    changed = runner._prepare_initial_locale_runtime(tmp_path, request())
    assert 'src/lib/request-locale.ts' in changed
    assert 'src/middleware.ts' in changed
    assert 'src/helloada.config.ts' not in changed
    assert presentation.read_text() == 'Ada owns the page composition'
    assert config.read_text() == 'Verified tenant config belongs to the release, not Ada'
    assert runner._prepare_initial_locale_runtime(tmp_path, request()) == ()


def test_every_image_alternative_is_staged_in_each_requested_language():
    from dataclasses import replace
    from types import SimpleNamespace

    selected = plan()
    opening = selected.page_composition[0]
    selected.page_composition = (replace(opening, entries=(*opening.entries,
        {'key': 'portrait', 'blockType': 'helloAdaImage', 'label': 'Portrait', 'asset_id': 'media-17'})),)
    selected.asset_composition_plan = (SimpleNamespace(asset_id='media-17'),)
    selected.copy_deck['image_alt'] = {'portrait': 'La estilista con su clienta.'}
    selected.copy_deck['translations']['en']['image_alt'] = {'portrait': 'The stylist with her client.'}
    value = request().to_dict()
    value['supplied_media_asset_ids'] = [17]
    target = PageBuildRequest.from_dict(value)
    payload = Payload()
    payload.read_media = lambda identifier, **_kwargs: {'id': int(identifier)}
    runner._stage_initial_homepage_payload({'payload_gateway': payload}, target, selected)
    assert payload.documents['es']['sections'][0]['entries'][-1]['alt'] == 'La estilista con su clienta.'
    assert payload.documents['en']['sections'][0]['entries'][-1]['alt'] == 'The stylist with her client.'
    del selected.copy_deck['translations']['en']['image_alt']['portrait']
    with pytest.raises(runner.RunnerError, match='image_alt'):
        runner._stage_initial_homepage_payload({'payload_gateway': payload}, target, selected)
