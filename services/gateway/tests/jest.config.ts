import type { Config } from 'jest';

const config: Config = {
  preset: 'ts-jest',
  testEnvironment: 'node',
  roots: ['<rootDir>/tests'],
  testMatch: ['**/*.ts', '!**/*.d.ts'],
  moduleFileExtensions: ['ts', 'js', 'json'],
  transform: {
    '^.+\\.ts$': ['ts-jest', {
      tsconfig: {
        target: 'ES2022',
        module: 'commonjs',
        esModuleInterop: true,
        strict: true,
        skipLibCheck: true,
      },
    }],
  },
  moduleNameMapper: {
    '^app/(.*)$': '<rootDir>/app/$1',
  },
  collectCoverageFrom: [
    'app/**/*.ts',
    '!app/**/*.d.ts',
  ],
  coverageDirectory: 'coverage',
  coverageReporters: ['text', 'lcov', 'clover'],
  clearMocks: true,
  resetMocks: true,
};

export default config;
