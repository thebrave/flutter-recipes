import os
import tempfile
import zipfile

from recipe_engine import recipe_test_api

class RecipeTestingTestApi(recipe_test_api.RecipeTestApi):

  def flutter_signing_identity(self, step_name=None):
    step_name = step_name or 'Setup keychain.show-identities'
    return self.step_data(
        step_name,
        stdout=self.m.raw_io.output_text(
            '1) ABCD "Developer ID Application: FLUTTER.IO LLC (ABCD)"'
        )
    )
