import sys
import unittest
from pathlib import Path
from datetime import datetime, timedelta, timezone
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from authorization import *

class TwoProfiles(unittest.TestCase):
    def principal(self, role, **kw):
        return Principal('m1', 'sqa', (Grant(role, 'sqa', 'm1', **kw),))

    def test_operator_work_and_denials(self):
        p = self.principal('operador')
        own = Resource('item', 'sqa', 'draft', 'm1')
        edition = Resource('edition', 'sqa', 'draft')
        for action, resource in [(ITEM_CREATE,None),(ITEM_EDIT,own),(ITEM_SUBMIT,own),(AI_REVISE,own),(EDITION_EDIT,edition),(EDITION_SUBMIT,edition),(AI_REVISE,edition)]:
            self.assertTrue(authorize(p, action, resource), action)
        for action, resource in [(ACCOUNTS_MANAGE,None),(ITEM_REVIEW,Resource('item','sqa','review')),(EDITION_APPROVE,Resource('edition_revision','sqa','pending_approval')),(PUBLICATION_EXPORT,Resource('publication','sqa','published'))]:
            self.assertFalse(authorize(p, action, resource), action)
        self.assertTrue(authorize(p,ITEM_READ,Resource('item','sqa','ready','other')))
        self.assertFalse(authorize(p,ITEM_EDIT,Resource('item','sqa','draft','other')))

    def test_admin_and_isolation(self):
        p=self.principal('administrador')
        self.assertTrue(authorize(p,ACCOUNTS_MANAGE))
        self.assertTrue(authorize(p,ITEM_REVIEW,Resource('item','sqa','review')))
        self.assertTrue(authorize(p,EDITION_APPROVE,Resource('edition_revision','sqa','pending_approval')))
        self.assertTrue(authorize(p,PUBLICATION_EXPORT,Resource('publication','sqa','published')))
        self.assertFalse(authorize(p,ITEM_READ,Resource('item','other','ready')))
        self.assertFalse(authorize(p,EDITION_EDIT,Resource('edition','sqa','draft',immutable=True)))
        self.assertFalse(authorize(p,EDITION_APPROVE,Resource('edition_revision','sqa','draft')))

    def test_expiration_revocation(self):
        past=datetime.now(timezone.utc)-timedelta(days=1)
        for role in PUBLIC_ROLES:
            self.assertFalse(authorize(self.principal(role,revoked_at=past),ITEM_CREATE))
            self.assertFalse(authorize(self.principal(role,valid_until=past),ITEM_CREATE))

if __name__=='__main__': unittest.main()
