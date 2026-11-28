@file:OptIn(kotlin.contracts.ExperimentalContracts::class)
package com.meztking.roundtable.data.browser

import kotlin.contracts.contract

// kotlin.test's asserts (argument order as there), over JUnit, for the tests ported from DSH Mobile.
fun <T> assertEquals(expected: T, actual: T, message: String? = null) = org.junit.Assert.assertEquals(message, expected, actual)
fun assertTrue(actual: Boolean, message: String? = null) = org.junit.Assert.assertTrue(message, actual)
fun assertFalse(actual: Boolean, message: String? = null) = org.junit.Assert.assertFalse(message, actual)
fun assertNull(actual: Any?, message: String? = null) = org.junit.Assert.assertNull(message, actual)
inline fun <reified T> assertIs(value: Any?, message: String? = null): T {
    contract { returns() implies (value is T) }
    if (value !is T) org.junit.Assert.fail(message ?: "expected ${T::class.simpleName}, got $value")
    return value as T
}
