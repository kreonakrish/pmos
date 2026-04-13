import { Router, Request, Response } from 'express';
import { v4 as uuidv4 } from 'uuid';
import { requirePermission, JwtPayload } from '../middleware/auth';
import {
  listUsers,
  listRoles,
  listPermissions,
  createUser,
  updateUser,
  deleteUser,
  setPassword,
  setUserRoles,
  findUserById,
  getUserAccess,
} from '../services/authService';
import { logger } from '../utils/logger';

const router = Router();

// -------------------- USERS --------------------
router.get('/users', requirePermission('users.read'), async (_req: Request, res: Response) => {
  const users = await listUsers();
  res.json({ users });
});

router.post('/users', requirePermission('users.write'), async (req: Request, res: Response) => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const actor = (req as Request & { user?: JwtPayload }).user;
  const {
    username, email, full_name, password, roles, must_change_password,
  } = (req.body ?? {}) as {
    username?: string; email?: string; full_name?: string;
    password?: string; roles?: string[]; must_change_password?: boolean;
  };
  if (!username || !email || !password || password.length < 8) {
    res.status(400).json({ error: 'username, email, password(≥8) required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }
  try {
    const user = await createUser({
      username,
      email,
      fullName: full_name ?? null,
      password,
      roles: roles ?? ['user'],
      mustChangePassword: must_change_password ?? true,
      grantedBy: actor?.uid ?? null,
    });
    logger.info('user_created', { trace_id: traceId, by: actor?.sub, username });
    const access = await getUserAccess(user.id);
    res.status(201).json({ ...user, ...access });
  } catch (err: unknown) {
    const msg = err instanceof Error ? err.message : 'create_error';
    if (msg.includes('Duplicate')) {
      res.status(409).json({ error: 'Username or email already exists', code: 'CONFLICT', trace_id: traceId });
      return;
    }
    logger.error('user_create_error', { trace_id: traceId, reason: msg });
    res.status(500).json({ error: 'Failed to create user', code: 'INTERNAL', trace_id: traceId });
  }
});

router.patch('/users/:id', requirePermission('users.write'), async (req: Request, res: Response) => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const id = Number(req.params.id);
  if (!Number.isFinite(id)) { res.status(400).json({ error: 'bad id', trace_id: traceId }); return; }
  const existing = await findUserById(id);
  if (!existing) { res.status(404).json({ error: 'not found', trace_id: traceId }); return; }
  const { email, full_name, status } = (req.body ?? {}) as {
    email?: string; full_name?: string | null; status?: 'active' | 'disabled' | 'locked';
  };
  await updateUser(id, { email, fullName: full_name, status });
  const updated = await findUserById(id);
  const access = updated ? await getUserAccess(updated.id) : { roles: [], permissions: [] };
  res.json({ ...updated, ...access });
});

router.put('/users/:id/roles', requirePermission('roles.assign'), async (req: Request, res: Response) => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const actor = (req as Request & { user?: JwtPayload }).user;
  const id = Number(req.params.id);
  if (!Number.isFinite(id)) { res.status(400).json({ error: 'bad id', trace_id: traceId }); return; }
  const { roles } = (req.body ?? {}) as { roles?: string[] };
  if (!Array.isArray(roles)) {
    res.status(400).json({ error: 'roles array required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }
  const existing = await findUserById(id);
  if (!existing) { res.status(404).json({ error: 'not found', trace_id: traceId }); return; }
  await setUserRoles(id, roles, actor?.uid ?? null);
  const access = await getUserAccess(id);
  logger.info('user_roles_updated', { trace_id: traceId, by: actor?.sub, user_id: id, roles });
  res.json({ user_id: id, ...access });
});

router.post('/users/:id/reset-password', requirePermission('users.write'), async (req: Request, res: Response) => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const id = Number(req.params.id);
  const { new_password } = (req.body ?? {}) as { new_password?: string };
  if (!new_password || new_password.length < 8) {
    res.status(400).json({ error: 'new_password (≥8) required', code: 'VALIDATION_ERROR', trace_id: traceId });
    return;
  }
  const existing = await findUserById(id);
  if (!existing) { res.status(404).json({ error: 'not found', trace_id: traceId }); return; }
  await setPassword(id, new_password, true); // force must_change_password on next login
  logger.info('user_password_reset', { trace_id: traceId, user_id: id });
  res.status(204).send();
});

router.delete('/users/:id', requirePermission('users.delete'), async (req: Request, res: Response) => {
  const traceId = (req as Request & { id?: string }).id ?? uuidv4();
  const actor = (req as Request & { user?: JwtPayload }).user;
  const id = Number(req.params.id);
  if (actor?.uid === id) {
    res.status(400).json({ error: 'Cannot delete your own account', code: 'SELF_DELETE', trace_id: traceId });
    return;
  }
  const existing = await findUserById(id);
  if (!existing) { res.status(404).json({ error: 'not found', trace_id: traceId }); return; }
  if (existing.is_system) {
    res.status(403).json({ error: 'Cannot delete system user', code: 'FORBIDDEN', trace_id: traceId });
    return;
  }
  await deleteUser(id);
  logger.info('user_deleted', { trace_id: traceId, by: actor?.sub, user_id: id });
  res.status(204).send();
});

// -------------------- ROLES --------------------
router.get('/roles', requirePermission('roles.read'), async (_req: Request, res: Response) => {
  const roles = await listRoles();
  res.json({ roles });
});

// -------------------- PERMISSIONS --------------------
router.get('/permissions', requirePermission('permissions.read'), async (_req: Request, res: Response) => {
  const permissions = await listPermissions();
  res.json({ permissions });
});

export default router;
