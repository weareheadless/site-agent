import * as migration_20261004_021536_helloada_initial from './20261004_021536_helloada_initial';
import * as migration_20261004_090000_growth_operations from './20261004_090000_growth_operations';
import * as migration_20261006_061835_helloada_owner_handoff from './20261006_061835_helloada_owner_handoff';
import * as migration_20261009_123644_helloada_mailbox_calendar from './20261009_123644_helloada_mailbox_calendar';

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
];
