import * as migration_20261004_021536_helloada_initial from './20261004_021536_helloada_initial';
import * as migration_20261004_090000_growth_operations from './20261004_090000_growth_operations';

export const migrations = [
  {
    up: migration_20261004_021536_helloada_initial.up,
    down: migration_20261004_021536_helloada_initial.down,
    name: '20261004_021536_helloada_initial'
  },
  {
    up: migration_20261004_090000_growth_operations.up,
    down: migration_20261004_090000_growth_operations.down,
    name: '20261004_090000_growth_operations'
  },
];
