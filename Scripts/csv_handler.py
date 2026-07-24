"""
Music Museum Toolkit
CSV Handler
Version 0.1 Foundation
"""

import pandas as pd
import os


def load_playlist():

    input_path = os.path.join(
        os.path.dirname(__file__),
        "..",
        "Input",
        "spotify_playlist_preservation.csv"
    )

    print("Loading playlist...")

    df = pd.read_csv(input_path)

    print(f"✓ {len(df)} songs loaded.\n")

    return df