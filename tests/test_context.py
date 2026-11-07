import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from citerag import context

class ContextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.output=self.root/'export'
        self.db=self.root/'sessions.db'
        con=sqlite3.connect(self.db)
        con.executescript('CREATE TABLE session_v2(id TEXT,directory TEXT,time_created INTEGER,time_updated INTEGER); CREATE TABLE session_message(id TEXT,session_id TEXT,type TEXT,seq INTEGER,time_created INTEGER,data TEXT);')
        con.execute('INSERT INTO session_v2 VALUES (?,?,?,?)',('s1','/approved',1,2))
        con.execute('INSERT INTO session_v2 VALUES (?,?,?,?)',('s2','/unapproved',1,2))
        payload={'content':[{'type':'text','text':'Approved answer'},{'type':'reasoning','text':'Never export reasoning'},{'type':'tool','text':'Never export tool output'}]}
        con.execute('INSERT INTO session_message VALUES (?,?,?,?,?,?)',('m1','s1','assistant',1,1,json.dumps(payload)))
        con.execute('INSERT INTO session_message VALUES (?,?,?,?,?,?)',('m2','s2','user',1,1,json.dumps({'text':'Unapproved private text'})))
        con.commit();con.close()
        self.config={'database':str(self.db),'session_directories':['/approved'],'sessions_per_directory':5,'max_messages_per_session':100,'max_session_characters':10000,'document_roots':{}}
        self.patcher=patch.object(context,'OUTPUT',self.output);self.patcher.start();self.addCleanup(self.patcher.stop)
    def test_preview_does_not_write(self):
        report=context.sync(self.config)
        self.assertEqual(report['documents'],1)
        self.assertFalse(self.output.exists())
    def test_roles_and_allowlist(self):
        context.sync(self.config,apply=True)
        body=next((self.output/'sessions').glob('*.md')).read_text()
        self.assertIn('Approved answer',body)
        self.assertNotIn('Never export',body)
        self.assertNotIn('Unapproved private',body)
        con=sqlite3.connect(self.db)
        self.assertEqual(con.execute('SELECT count(*) FROM session_message').fetchone()[0],2)
        con.close()
    def test_incremental_and_deleted_owned_source(self):
        first=context.sync(self.config,apply=True)
        second=context.sync(self.config,apply=True)
        self.assertEqual(second['unchanged'],first['documents'])
        self.config['session_directories']=[]
        third=context.sync(self.config,apply=True)
        self.assertEqual(third['removed'],1)
        self.assertFalse(list((self.output/'sessions').glob('*.md')))
    def test_redaction(self):
        secret='sk-'+'A'*40
        text='api_key="'+secret+'"\nAuthorization: Bearer '+('B'*30)+'\nhttps://user:password@example.org/'
        clean,counts=context.redact(text)
        self.assertNotIn(secret,clean)
        self.assertNotIn('B'*30,clean)
        self.assertNotIn('user:password',clean)
        self.assertTrue(counts)
    def test_private_key_redaction(self):
        clean,_=context.redact('-----BEGIN '+'PRIVATE KEY-----\nprivate material\n-----END '+'PRIVATE KEY-----')
        self.assertNotIn('private material',clean)
    def test_output_symlink_is_rejected(self):
        target=self.root/'elsewhere';target.mkdir();self.output.symlink_to(target,target_is_directory=True)
        with self.assertRaises(ValueError):context.sync(self.config,apply=True)
    def test_text_extraction_ignores_nontext(self):
        self.assertEqual(context.plain_text('assistant',{'content':[{'type':'tool','text':'secret'}]}),'')
        self.assertEqual(context.plain_text('system',{'text':'system instructions'}),'')
    def test_database_url_and_opaque_auth_redaction(self):
        text='postgresql://user:pw@db/name\nredis://user:pw@db\nAuthorization: opaque-private-value'
        clean,_=context.redact(text)
        self.assertNotIn('user:pw',clean)
        self.assertNotIn('opaque-private-value',clean)
    def test_manifest_symlink_is_rejected(self):
        self.output.mkdir();target=self.root/'outside';target.write_text('{}')
        (self.output/'manifest.json').symlink_to(target)
        with self.assertRaises(ValueError):context.sync(self.config,apply=True)
        self.assertEqual(target.read_text(),'{}')
    def test_user_modified_file_is_preserved(self):
        context.sync(self.config,apply=True)
        path=next((self.output/'sessions').glob('*.md'));path.write_text('User edit')
        self.config['session_directories']=[]
        report=context.sync(self.config,apply=True)
        self.assertEqual(path.read_text(),'User edit')
        self.assertEqual(len(report['conflicts']),1)
    def test_predictable_temp_symlink_is_not_followed(self):
        context.sync(self.config,apply=True)
        path=next((self.output/'sessions').glob('*.md'))
        target=self.root/'outside';target.write_text('Keep')
        path.with_suffix('.md.tmp').symlink_to(target)
        context.atomic_write(path,'Changed')
        self.assertEqual(target.read_text(),'Keep')
    def test_user_modified_file_is_preserved_on_source_update(self):
        context.sync(self.config,apply=True)
        path=next((self.output/'sessions').glob('*.md'));path.write_text('User edit')
        con=sqlite3.connect(self.db)
        con.execute('UPDATE session_message SET data=? WHERE id=?',(json.dumps({'content':[{'type':'text','text':'Updated source'}]}),'m1'))
        con.commit();con.close()
        report=context.sync(self.config,apply=True)
        self.assertEqual(path.read_text(),'User edit')
        self.assertEqual(len(report['conflicts']),1)
    def test_unanswered_probe_session_is_not_knowledge(self):
        con=sqlite3.connect(self.db)
        con.execute('UPDATE session_message SET type=?,data=? WHERE id=?',('user',json.dumps({'text':'A failed probe question'}),'m1'))
        con.commit();con.close()
        report=context.sync(self.config,apply=True)
        self.assertEqual(report['documents'],0)
        self.assertEqual(report['skipped_unanswered_sessions'],1)
