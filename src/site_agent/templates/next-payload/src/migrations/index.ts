import * as migration_20261004_021536_helloada_initial from './20261004_021536_helloada_initial';
import * as migration_20261004_090000_growth_operations from './20261004_090000_growth_operations';
import * as migration_20261006_061835_helloada_owner_handoff from './20261006_061835_helloada_owner_handoff';

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
    name: '20261006_061835_helloada_owner_handoff'
  },
];
