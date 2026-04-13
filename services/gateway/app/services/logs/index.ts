import { LogSource } from './LogSource';
import { DockerLogSource } from './DockerLogSource';
import { config } from '../../config';
import { logger } from '../../utils/logger';

let instance: LogSource | null = null;

export function getLogSource(): LogSource {
  if (instance) return instance;

  switch (config.LOG_SOURCE) {
    case 'docker':
      instance = new DockerLogSource(config.DOCKER_SOCKET_PATH);
      break;
    // case 'k8s':  instance = new KubernetesLogSource(...); break;
    // case 'loki': instance = new LokiLogSource(...);       break;
    default:
      throw new Error(`unsupported LOG_SOURCE: ${config.LOG_SOURCE}`);
  }

  logger.info('log_source_initialized', { layer: 'service', impl: config.LOG_SOURCE });
  return instance;
}

export * from './LogSource';
