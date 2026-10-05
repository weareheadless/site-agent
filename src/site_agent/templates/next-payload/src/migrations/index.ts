import * as migration_20261004_021536_helloada_initial from './20261004_021536_helloada_initial';
import * as migration_20261004_221500_growth_operations from './20261004_221500_growth_operations';
import * as migration_20261004_232326_helloada_messages_contacts from './20261004_232326_helloada_messages_contacts';

export const migrations = [
  {
    up: migration_20261004_021536_helloada_initial.up,
    down: migration_20261004_021536_helloada_initial.down,
    name: '20261004_021536_helloada_initial',
  },
  {
    up: migration_20261004_221500_growth_operations.up,
    down: migration_20261004_221500_growth_operations.down,
    name: '20261004_221500_growth_operations',
  },
  {
    up: migration_20261004_232326_helloada_messages_contacts.up,
    down: migration_20261004_232326_helloada_messages_contacts.down,
    name: '20261004_232326_helloada_messages_contacts'
  },
];
