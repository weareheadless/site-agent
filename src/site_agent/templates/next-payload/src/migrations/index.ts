import * as migration_20261004_021536_helloada_initial from './20261004_021536_helloada_initial';
import * as migration_20261004_090000_growth_operations from './20261004_090000_growth_operations';
import * as migration_20261006_061835_helloada_owner_handoff from './20261006_061835_helloada_owner_handoff';
import * as migration_20261009_123644_helloada_mailbox_calendar from './20261009_123644_helloada_mailbox_calendar';
import * as migration_20261031_090000_helloada_section_layout from './20261031_090000_helloada_section_layout';
import * as migration_20261104_010000_business_catalog from './20261104_010000_business_catalog';
import * as migration_20261104_170000_category_criteria from './20261104_170000_category_criteria';
import * as migration_20261104_190000_category_drafts from './20261104_190000_category_drafts';
import * as migration_20261104_220000_category_version_backfill from './20261104_220000_category_version_backfill';
import * as migration_20261105_020000_localized_catalog_facts from './20261105_020000_localized_catalog_facts';

export const migrations = [
  {
    up: migration_20261004_021536_helloada_initial.up,
    down: migration_20261004_021536_helloada_initial.down,
    name: '20261004_021536_helloada_initial',
  },
  {
    up: migration_20261004_090000_growth_operations.up,
    down: migration_20261004_090000_growth_operations.down,
    name: '20261004_090000_growth_operations',
  },
  {
    up: migration_20261006_061835_helloada_owner_handoff.up,
    down: migration_20261006_061835_helloada_owner_handoff.down,
    name: '20261006_061835_helloada_owner_handoff',
  },
  {
    up: migration_20261009_123644_helloada_mailbox_calendar.up,
    down: migration_20261009_123644_helloada_mailbox_calendar.down,
    name: '20261009_123644_helloada_mailbox_calendar'
  },
  {
    up: migration_20261031_090000_helloada_section_layout.up,
    down: migration_20261031_090000_helloada_section_layout.down,
    name: '20261031_090000_helloada_section_layout'
  },
  {
    up: migration_20261104_010000_business_catalog.up,
    down: migration_20261104_010000_business_catalog.down,
    name: '20261104_010000_business_catalog'
  },
  {
    up: migration_20261104_170000_category_criteria.up,
    down: migration_20261104_170000_category_criteria.down,
    name: '20261104_170000_category_criteria'
  },
  {
    up: migration_20261104_190000_category_drafts.up,
    down: migration_20261104_190000_category_drafts.down,
    name: '20261104_190000_category_drafts'
  },
  {
    up: migration_20261104_220000_category_version_backfill.up,
    down: migration_20261104_220000_category_version_backfill.down,
    name: '20261104_220000_category_version_backfill'
  },
  {
    up: migration_20261105_020000_localized_catalog_facts.up,
    down: migration_20261105_020000_localized_catalog_facts.down,
    name: '20261105_020000_localized_catalog_facts'
  },
];
