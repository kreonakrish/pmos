from typing import Any, Dict, List, Optional

import mysql.connector

from app.adapters.base import SearchResult
from app.utils.logger import get_logger

logger = get_logger(layer="adapter")


class MySQLFullTextAdapter:
    """
    Full-text search adapter using MySQL MATCH ... AGAINST.
    Not a VectorStoreAdapter because it operates on text, not vectors.
    """

    def __init__(self, settings) -> None:
        self._host = settings.mysql_host
        self._port = settings.mysql_port
        self._db = settings.mysql_db
        self._user = settings.mysql_user
        self._password = settings.mysql_password

    def _connect(self):
        return mysql.connector.connect(
            host=self._host,
            port=self._port,
            database=self._db,
            user=self._user,
            password=self._password,
            connection_timeout=5,
        )

    async def search(
        self, query: str, k: int, filters: Optional[dict] = None
    ) -> List[SearchResult]:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            return await loop.run_in_executor(ex, self._search_sync, query, k, filters)

    def _search_sync(
        self, query: str, k: int, filters: Optional[dict]
    ) -> List[SearchResult]:
        """Search chunk content first (real text); fall back to filename match.

        rag_chunks.content has no FULLTEXT index, so we use a LIKE-based
        keyword OR match. Splits query into non-trivial tokens and matches
        any of them; ranks by number of matched tokens.
        """
        results: List[SearchResult] = []
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor(dictionary=True)

            # ---- 1. chunk-content search ----
            tokens = [t for t in (query or "").split() if len(t) >= 3][:8]
            if tokens:
                where = " OR ".join(["c.content LIKE %s"] * len(tokens))
                score_expr = " + ".join(["(c.content LIKE %s)"] * len(tokens))
                like_params = [f"%{t}%" for t in tokens]
                sql = f"""
                    SELECT c.chunk_id, c.document_id, c.chunk_index, c.content,
                           d.filename, d.content_type, d.team_id, d.agent_id,
                           ({score_expr}) AS match_score
                      FROM rag_chunks c
                      JOIN rag_documents d ON d.document_id = c.document_id
                     WHERE {where}
                     ORDER BY match_score DESC, c.chunk_index ASC
                     LIMIT %s
                """
                cursor.execute(sql, (*like_params, *like_params, k))
                rows = cursor.fetchall() or []
                for row in rows:
                    ms = int(row.get("match_score") or 0)
                    score = min(1.0, 0.3 + 0.1 * ms)  # at least one token matched → 0.4
                    results.append(
                        SearchResult(
                            id=str(row.get("chunk_id") or row.get("document_id") or ""),
                            content=str(row.get("content") or ""),
                            score=score,
                            source="mysql",
                            metadata={
                                "filename": row.get("filename"),
                                "document_id": row.get("document_id"),
                                "chunk_index": row.get("chunk_index"),
                                "team_id": row.get("team_id"),
                                "agent_id": row.get("agent_id"),
                            },
                        )
                    )
                if results:
                    return results

            # ---- 2. fallback: filename match, return real chunk text ----
            like_q = f"%{query}%"
            cursor.execute(
                """
                SELECT c.chunk_id, c.document_id, c.chunk_index, c.content,
                       d.filename, d.team_id, d.agent_id
                  FROM rag_chunks c
                  JOIN rag_documents d ON d.document_id = c.document_id
                 WHERE d.filename LIKE %s OR d.document_id LIKE %s
                 ORDER BY d.created_at DESC, c.chunk_index ASC
                 LIMIT %s
                """,
                (like_q, like_q, k),
            )
            for row in cursor.fetchall() or []:
                results.append(
                    SearchResult(
                        id=str(row.get("chunk_id") or ""),
                        content=str(row.get("content") or ""),
                        score=0.5,
                        source="mysql",
                        metadata={
                            "filename": row.get("filename"),
                            "document_id": row.get("document_id"),
                            "chunk_index": row.get("chunk_index"),
                            "team_id": row.get("team_id"),
                            "agent_id": row.get("agent_id"),
                        },
                    )
                )
        except Exception as exc:
            logger.error("MySQL full-text search failed", error=str(exc))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass
        return results

    async def insert_document(
        self,
        doc_id: str,
        content: str,
        filename: str,
        team_id: str,
        agent_id: int,
        conversation_id: Optional[str] = None,
        chunk_count: int = 1,
    ) -> None:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(
                ex, self._insert_sync, doc_id, content, filename, team_id, agent_id, conversation_id, chunk_count
            )

    def _insert_sync(
        self,
        doc_id: str,
        content: str,
        filename: str,
        team_id: str,
        agent_id: int,
        conversation_id: Optional[str] = None,
        chunk_count: int = 1,
    ) -> None:
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            # Determine content_type from filename extension
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'txt'
            mime_map = {'pdf': 'application/pdf', 'csv': 'text/csv', 'json': 'application/json',
                        'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                        'md': 'text/markdown'}
            content_type = mime_map.get(ext, 'text/plain')
            file_size = len(content.encode('utf-8')) if content else 0

            sql = """
                INSERT INTO rag_documents (document_id, filename, content_type, file_size, chunk_count, status, agent_id, team_id, conversation_id)
                VALUES (%s, %s, %s, %s, %s, 'INDEXED', %s, %s, %s)
                ON DUPLICATE KEY UPDATE status = 'INDEXED', chunk_count = VALUES(chunk_count), updated_at = NOW()
            """
            cursor.execute(sql, (doc_id, filename, content_type, file_size, chunk_count, str(agent_id), team_id, conversation_id))
            conn.commit()
        except Exception as exc:
            logger.error("MySQL document insert failed", error=str(exc))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    async def insert_chunks(
        self,
        doc_id: str,
        chunks: List[Dict[str, Any]],
    ) -> None:
        """Bulk-insert chunks to rag_chunks.

        Each chunk dict must have: chunk_id, chunk_index, content.
        Optional: embedding_id, metadata.
        """
        if not chunks:
            return
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(ex, self._insert_chunks_sync, doc_id, chunks)

    def _insert_chunks_sync(self, doc_id: str, chunks: List[Dict[str, Any]]) -> None:
        import json as _json
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            # Clear any prior chunks for this doc (idempotent re-ingest)
            cursor.execute("DELETE FROM rag_chunks WHERE document_id = %s", (doc_id,))
            rows = [
                (
                    c["chunk_id"],
                    doc_id,
                    int(c.get("chunk_index", 0)),
                    c.get("content", "") or "",
                    c.get("embedding_id"),
                    _json.dumps(c.get("metadata") or {}),
                )
                for c in chunks
            ]
            cursor.executemany(
                """
                INSERT INTO rag_chunks (chunk_id, document_id, chunk_index, content, embedding_id, metadata)
                VALUES (%s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
            conn.commit()
        except Exception as exc:
            logger.error("MySQL chunk insert failed", error=str(exc), doc_id=doc_id, n=len(chunks))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    async def get_document(self, doc_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a single document's full metadata by ID."""
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            return await loop.run_in_executor(ex, self._get_document_sync, doc_id)

    def _get_document_sync(self, doc_id: str) -> Optional[Dict[str, Any]]:
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, document_id, filename, content_type, file_size, chunk_count, "
                "status, agent_id, team_id, conversation_id, created_at, updated_at "
                "FROM rag_documents WHERE document_id = %s OR id = %s",
                (doc_id, doc_id),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "id": str(row.get("id", "")),
                    "document_id": row.get("document_id", ""),
                    "filename": row.get("filename", ""),
                    "content_type": row.get("content_type", ""),
                    "file_size": row.get("file_size", 0),
                    "chunk_count": row.get("chunk_count", 0),
                    "status": row.get("status", ""),
                    "team_id": row.get("team_id", ""),
                    "agent_id": row.get("agent_id", ""),
                    "conversation_id": row.get("conversation_id"),
                    "created_at": str(row.get("created_at", "")),
                }
            return None
        except Exception as exc:
            logger.error("MySQL get document failed", error=str(exc))
            return None
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    async def list_documents(self) -> list:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            return await loop.run_in_executor(ex, self._list_documents_sync)

    def _list_documents_sync(self) -> list:
        results = []
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                "SELECT id, document_id, filename, content_type, file_size, chunk_count, "
                "status, agent_id, team_id, conversation_id, created_at, updated_at "
                "FROM rag_documents ORDER BY created_at DESC LIMIT 100"
            )
            rows = cursor.fetchall()
            for row in rows:
                results.append({
                    "id": str(row.get("id", "")),
                    "document_id": row.get("document_id", ""),
                    "filename": row.get("filename", ""),
                    "content_type": row.get("content_type", ""),
                    "file_size": row.get("file_size", 0),
                    "chunk_count": row.get("chunk_count", 0),
                    "status": row.get("status", "INDEXED"),
                    "team_id": row.get("team_id", ""),
                    "agent_id": row.get("agent_id", ""),
                    "conversation_id": row.get("conversation_id", ""),
                    "created_at": str(row.get("created_at", "")),
                    "updated_at": str(row.get("updated_at", "")),
                })
        except Exception as exc:
            logger.error("MySQL list documents failed", error=str(exc))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass
        return results

    async def get_document_chunks(self, doc_id: str) -> list:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            return await loop.run_in_executor(ex, self._get_chunks_sync, doc_id)

    def _get_chunks_sync(self, doc_id: str) -> list:
        results = []
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor(dictionary=True)
            cursor.execute(
                """
                SELECT c.chunk_id, c.document_id, c.chunk_index, c.content, c.metadata,
                       d.filename
                  FROM rag_chunks c
                  JOIN rag_documents d ON d.document_id = c.document_id
                 WHERE c.document_id = %s OR d.id = %s
                 ORDER BY c.chunk_index ASC
                """,
                (doc_id, doc_id),
            )
            for row in cursor.fetchall() or []:
                results.append({
                    "chunk_id": row.get("chunk_id"),
                    "chunk_index": row.get("chunk_index", 0),
                    "content": row.get("content", ""),
                    "doc_id": row.get("document_id"),
                    "filename": row.get("filename"),
                    "metadata": row.get("metadata"),
                })
        except Exception as exc:
            logger.error("MySQL get chunks failed", error=str(exc))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass
        return results

    async def delete_document(self, doc_id: str) -> None:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(ex, self._delete_sync, doc_id)

    def _delete_sync(self, doc_id: str) -> None:
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("DELETE FROM rag_chunks WHERE document_id = %s", (doc_id,))
            cursor.execute("DELETE FROM rag_documents WHERE document_id = %s OR id = %s", (doc_id, doc_id))
            conn.commit()
        except Exception as exc:
            logger.error("MySQL document delete failed", error=str(exc))
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass

    async def health_check(self) -> bool:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            return await loop.run_in_executor(ex, self._health_sync)

    def _health_sync(self) -> bool:
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()  # consume result to avoid "Unread result found"
            return True
        except Exception as exc:
            logger.error("MySQL health check failed", error=str(exc))
            return False
        finally:
            try:
                if cursor:
                    cursor.close()
                if conn:
                    conn.close()
            except Exception:
                pass
