/********************************************************************************
 * Copyright (c) 2025 Contributors to the Eclipse Foundation
 *
 * See the NOTICE file(s) distributed with this work for additional
 * information regarding copyright ownership.
 *
 * This program and the accompanying materials are made available under the
 * terms of the Apache License Version 2.0 which is available at
 * https://www.apache.org/licenses/LICENSE-2.0
 *
 * SPDX-License-Identifier: Apache-2.0
 ********************************************************************************/

/// interface macro derives the necessary traits and implementations for a given interface definition,
/// including its consumer and producer types, based on the provided event definitions.
/// It simplifies the creation of COM-API interfaces by generating boilerplate code for subscribing to events and offering services.
/// It use the syntactic wrappers in the input to determine between events, methods and fields,
/// but currently only supports event definitions.
/// Method and field definitions will result in a compile error,
/// indicating that they are not supported in the current version of the macro.
/// The macro generates a consumer struct with subscribers for each defined event
/// and a producer struct with publishers for each event,
/// along with the necessary trait implementations to integrate with the COM-API framework.
///
/// Parameters:
/// - `$interface_id`: The unique identifier for the interface, used in the Interface trait implementation
/// - `$interface`: The type of the interface for which the consumer and producer are being defined
/// - `$consumer`: The name of the consumer struct to be generated
/// - `$producer`: The name of the producer struct to be generated
/// - `$offered_producer`: The name of the offered producer struct to be generated
/// - `$event_name`: The name of the event for which a subscriber and publisher will be generated
/// - `$event_type`: The type of the event data associated with the event
/// Example usage:
/// ```
/// com_api_concept_interface_macros::interface!(
///    VehicleInterface,
///   crate::VehicleInterface,
///   VehicleConsumer,
///  VehicleProducer,
/// VehicleOfferedProducer,
/// left_tire : Event<crate::Tire>,
/// exhaust : Event<crate::Exhaust>
/// );
/// ```
/// This example defines a `VehicleInterface` with two events, `left_tire` and `exhaust`,
/// and generates the corresponding consumer and producer types with the necessary COM-API trait implementations.
#[macro_export]
macro_rules! interface {
    ($interface_id: ident, $interface:ty, $consumer:ident, $producer:ident, $offered_producer:ident, $($event_name:ident : Event<$event_type:ty>),+$(,)?) => {

        com_api_concept_interface_macros::interface_common!($interface_id, $consumer, $producer, $interface);
        com_api_concept_interface_macros::interface_consumer!($consumer,$($event_name, Event<$event_type>),+);
        com_api_concept_interface_macros::interface_producer!($producer, $offered_producer, $interface,$($event_name, Event<$event_type>),+);
    };

    ($interface_id: ident, $interface:ty, $consumer:ident, $producer:ident, $offered_producer:ident, $($method_name:ident : Method<$method_type:ty>),+$(,)?) => {

     com_api_concept_interface_macros::interface_common!($interface_id, $consumer, $producer, $interface);
        // For method definitions, we can implement a different macro or just ignore them for now
        // as the current focus is on event-based interfaces. Method handling would require a more complex design.
         compile_error!("Method definitions are not supported in this macro version. Please use Event<T> syntax for defining events.");

    };

    ($interface_id: ident, $interface:ty, $consumer:ident, $producer:ident, $offered_producer:ident, $($method_name:ident : Field<$method_type:ty>),+$(,)?) => {
        com_api_concept_interface_macros::interface_common!($interface_id, $consumer, $producer, $interface);
            // For field definitions, we can implement a different macro or just ignore them for now
            // as the current focus is on event-based interfaces. Method handling would require a more complex design.
            compile_error!("Field definitions are not supported in this macro version. Please use Event<T> syntax for defining events.");

    };

}

/// Macro to implement the Interface trait for a given interface type, consumer, and producer types.
/// As it is common for both consumer and producer, so it is part of the common macro.
#[macro_export]
macro_rules! interface_common {
    ($uid:ident, $consumer:ident, $producer:ident, $ty:path) => {
        impl com_api::Interface for $ty {
            const INTERFACE_ID: &'static str = stringify!($uid);
            type Consumer<R: com_api::Runtime + ?Sized> = $consumer<R>;
            type Producer<R: com_api::Runtime + ?Sized> = $producer<R>;
        }
    };
}

/// Macro to implement the Consumer trait for a given consumer type and its events.
#[macro_export]
macro_rules! interface_consumer {
    ($consumer:ident,$($event_name:ident, Event<$event_type:ty>),+$(,)?) => {
        pub struct $consumer<R: com_api::Runtime + ?Sized> {
            $(
                pub $event_name: R::Subscriber<$event_type>,
            )+
        }
        impl<R: com_api::Runtime + ?Sized> com_api::Consumer<R> for $consumer<R> {
            fn new(instance_info: R::ConsumerInfo) -> Self {
                $consumer {
                    $(
                        $event_name: R::Subscriber::new(
                            stringify!($event_name),
                            instance_info.clone()
                        ).expect(&format!("Failed to create subscriber for {}", stringify!($event_name))),
                    )+
                }
            }
        }
    };
}

/// Macro to implement the Producer and OfferedProducer traits for given producer and offered producer types and their events.
#[macro_export]
macro_rules! interface_producer {
    ($producer:ident,$offered_producer:ident,$interface:ty,$($event_name:ident, Event<$event_type:ty>),+$(,)?) => {
        pub struct $producer<R: com_api::Runtime + ?Sized> {
            _runtime: core::marker::PhantomData<R>,
            instance_info: R::ProviderInfo,
        }

        pub struct $offered_producer<R: com_api::Runtime + ?Sized> {
            $(
                pub $event_name: R::Publisher<$event_type>,
            )+
            instance_info: R::ProviderInfo,
        }

        impl<R: com_api::Runtime + ?Sized> com_api::Producer<R> for $producer<R> {
            type Interface = $interface;
            type OfferedProducer = $offered_producer<R>;
            fn offer(self) -> com_api::Result<Self::OfferedProducer> {
                let offered = $offered_producer {
                    $(
                        $event_name: R::Publisher::new(
                            stringify!($event_name),
                            self.instance_info.clone()
                        ).expect(&format!("Failed to create publisher for {}", stringify!($event_name))),
                    )+
                    instance_info: self.instance_info.clone(),
                };
                // Offer the service instance to make it discoverable
                self.instance_info.offer_service()?;
                Ok(offered)
            }

            fn new(instance_info: R::ProviderInfo) -> com_api::Result<Self> {
                Ok($producer {
                    _runtime: core::marker::PhantomData,
                    instance_info,
                })
            }
        }

        impl<R: com_api::Runtime + ?Sized> com_api::OfferedProducer<R> for $offered_producer<R> {
            type Interface = $interface;
            type Producer = $producer<R>;

            fn unoffer(self) -> com_api::Result<Self::Producer> {
                let producer = $producer {
                    _runtime: core::marker::PhantomData,
                    instance_info: self.instance_info.clone(),
                };
                // Stop offering the service instance to withdraw it from system availability
                self.instance_info.stop_offer_service()?;
                Ok(producer)
            }
        }
    };
}
