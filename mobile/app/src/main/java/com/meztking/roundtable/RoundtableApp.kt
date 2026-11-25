package com.meztking.roundtable

import android.app.Application
import com.meztking.roundtable.data.Store

class RoundtableApp : Application() {
    val store: Store by lazy { Store(this) }
}
