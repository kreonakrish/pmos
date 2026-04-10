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
        results: List[SearchResult] = []
        conn = None
        cursor = None
        try:
            conn = self._connect()
            cursor = conn.cursor(dictionary=True)
            # The rag_documents table has no full-text content column;
            # search by filename match as a lightweight fallback
            sql = """
                SELECT
                    id, document_id, filename, content_type, file_size,
                    chunk_count, status, team_id, agent_id, created_at
                FROM rag_documents
                WHERE filename LIKE %s OR document_id LIKE %s
                ORDER BY created_at DESC
                LIMIT %s
            """
            like_q = f"%{query}%"
            cursor.execute(sql, (like_q, like_q, k))
            rows = cursor.fetchall()
            for row in rows:
                results.append(
                    SearchResult(
                        id=str(row.get("document_id", row.get("id", ""))),
                        content=f"Document: {row.get('filename', '')} ({row.get('content_type', '')})",
                        score=1.0,
                        source="mysql",
                        metadata={
                            "filename": row.get("filename"),
                            "team_id": row.get("team_id"),
                            "agent_id": row.get("agent_id"),
                            "created_at": str(row.get("created_at", "")),
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
    ) -> None:
        import asyncio
        from concurrent.futures import ThreadPoolExecutor

        loop = asyncio.get_event_loop()
        with ThreadPoolExecutor(max_workers=1) as ex:
            await loop.run_in_executor(
                ex, self._insert_sync, doc_id, content, filename, team_id, agent_id, conversation_id
            )

    def _insert_sync(
        self,
        doc_id: str,
        content: str,
        filename: str,
        team_id: str,
        agent_id: int,
        conversation_id: Optional[str] = None,
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
                VALUES (%s, %s, %s, %s, 1, 'INDEXED', %s, %s, %s)
                ON DUPLICATE KEY UPDATE status = 'INDEXED', chunk_count = chunk_count + 1, updated_at = NOW()
            """
            cursor.execute(sql, (doc_id, filename, content_type, file_size, str(agent_id), team_id, conversation_id))
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
                "SELECT id, document_id, filename, chunk_count FROM rag_documents "
                "WHERE document_id = %s OR id = %s",
                (doc_id, doc_id),
            )
            row = cursor.fetchone()
            if row:
                chunk_count = row.get("chunk_count", 1)
                for i in range(chunk_count):
                    results.append({
                        "chunk_index": i,
                        "content": f"Chunk {i} of {row.get('filename', doc_id)} (stored in vector DB)",
                        "doc_id": row.get("document_id", doc_id),
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
